"""
Hír- és program-aggregátor: Google News RSS és zalaegerszegturizmus.hu HTML scrape.

Használat:
    from lib.news_fetcher import fetch_google_news, fetch_article_content, fetch_events, download_image

A fetch_news.py script ezeket hívja periodikusan.
"""

import hashlib
import io
import os
import re
import uuid
from datetime import datetime
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from PIL import Image

# 10 mp timeout, normál böngésző UA — sokan blokkolják a sima python-requests-et.
HTTP_TIMEOUT = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.5",
}

# Kép tárolása: <repo>/static/news_images/  → Flask static folder alatt,
# url_for('static', filename='news_images/xxx.webp')-vel elérhető.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_IMAGE_DIR = os.path.join(_REPO_ROOT, "static", "news_images")


# ─────────────────────────────────────────────────────────────────────
# Google News RSS
# ─────────────────────────────────────────────────────────────────────

GOOGLE_NEWS_QUERIES = {
    "local": "zalaegerszeg",
    "county": "zala+megye",
}


def google_news_rss_url(query: str) -> str:
    """Magyar nyelvű Google News RSS keresési URL."""
    return f"https://news.google.com/rss/search?q={query}&hl=hu&gl=HU&ceid=HU:hu"


def fetch_google_news(category: str, max_items: int = 50) -> list[dict]:
    """Visszaadja a frissítendő hír-itemeket. Még nem fetcheli a forrás cikket
    (azt később az ai-summary-hez kell), csak az RSS metadatát.

    Returns: list of {
        external_id, source_url (Google news redirect URL),
        source_name (forrás portál), title, published_at (datetime|None)
    }
    """
    query = GOOGLE_NEWS_QUERIES.get(category)
    if not query:
        return []

    feed = feedparser.parse(google_news_rss_url(query))
    items = []
    for entry in feed.entries[:max_items]:
        # source: a Google külön mezőben adja
        source_name = ""
        if hasattr(entry, "source") and entry.source:
            source_name = entry.source.get("title", "") if hasattr(entry.source, "get") else getattr(entry.source, "title", "")

        # published_parsed → datetime
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6])
            except (ValueError, TypeError):
                pass

        # external_id: a Google guid stabil, jó dedup-hoz
        ext_id = entry.get("id") or entry.get("link") or ""
        if not ext_id:
            continue

        items.append({
            "external_id": ext_id[:500],  # truncated to fit column
            "source_url": entry.get("link", ""),  # Google news redirect URL
            "source_name": source_name[:120] if source_name else "",
            "title": entry.get("title", "")[:500],
            "published_at": published_at,
        })
    return items


def resolve_real_url(google_news_url: str) -> str | None:
    """A Google News redirect URL-jét követve visszaadja az igazi forrás URL-t.
    A Google news.google.com/articles/... → 301/302 → tényleges portál."""
    try:
        resp = requests.get(
            google_news_url,
            headers=HEADERS,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        if resp.ok:
            return resp.url
    except requests.RequestException:
        pass
    return None


def fetch_article_content(url: str) -> dict:
    """Cikk HTML letöltése, OG image + body szöveg kiemelése.

    Returns: {
        real_url (a redirect után), og_image (URL|None),
        og_description (str), content (kibányászott body szöveg, max 8000 char)
    }
    """
    out = {"real_url": url, "og_image": None, "og_description": "", "content": ""}
    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=HTTP_TIMEOUT, allow_redirects=True
        )
        if not resp.ok:
            return out
        out["real_url"] = resp.url
        soup = BeautifulSoup(resp.text, "lxml")

        # OG image
        og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_img and og_img.get("content"):
            out["og_image"] = urljoin(resp.url, og_img["content"].strip())

        # OG description (fallback ha nincs body extractolható)
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            out["og_description"] = og_desc["content"].strip()[:1000]

        # Body szöveg: <article>, <main>, vagy a leghosszabb <div>
        article = soup.find("article") or soup.find("main")
        if not article:
            # Egyszerű fallback: minden <p>-t összeszedünk
            ps = soup.find_all("p")
            content = " ".join(p.get_text(" ", strip=True) for p in ps if p.get_text(strip=True))
        else:
            for tag in article(["script", "style", "nav", "aside", "form", "iframe"]):
                tag.decompose()
            content = article.get_text(" ", strip=True)
        # Whitespace normalizálás + truncate
        content = re.sub(r"\s+", " ", content).strip()
        out["content"] = content[:8000]
    except requests.RequestException:
        pass
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────────────
# Programok — zalaegerszegturizmus.hu/programok/
# ─────────────────────────────────────────────────────────────────────

EVENTS_URL = "https://zalaegerszegturizmus.hu/programok/"

HU_MONTH = {
    "január": 1, "február": 2, "március": 3, "április": 4, "május": 5, "június": 6,
    "július": 7, "augusztus": 8, "szeptember": 9, "október": 10, "november": 11, "december": 12,
}


def _parse_hu_date(text: str) -> datetime | None:
    """'2026 május 20' / 'május 20 2026' formátumú dátum parser."""
    if not text:
        return None
    text = text.lower().strip()
    # próbáljuk megtalálni a hónap nevét és a két számot
    month = None
    for name, num in HU_MONTH.items():
        if name in text:
            month = num
            text_wo = text.replace(name, " ")
            break
    if not month:
        return None
    nums = re.findall(r"\d+", text_wo)
    if len(nums) < 2:
        return None
    # Egy 4-jegyű az év, egy 1-2 jegyű a nap
    year = next((int(n) for n in nums if len(n) == 4), None)
    day = next((int(n) for n in nums if len(n) <= 2), None)
    if not year or not day:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def fetch_events(max_items: int = 50) -> list[dict]:
    """A zalaegerszegturizmus.hu/programok/ lista oldal scrape.
    Minden esemény részletes oldalához is le kell menni a kép + leírás miatt.

    Returns: list of {
        external_id, source_url, source_name (zalaegerszegturizmus.hu),
        title, event_start_at, event_end_at, event_location,
        image_url, description (a részletes oldalról).
    }
    """
    items = []
    try:
        resp = requests.get(EVENTS_URL, headers=HEADERS, timeout=HTTP_TIMEOUT)
        if not resp.ok:
            return items
        soup = BeautifulSoup(resp.text, "lxml")

        # A jelenleg ismert szerkezet: dátum + cím link. Keresünk minden olyan
        # <a>-t ami egyedi program-aloldalra mutat (/programok/<slug>/ vagy
        # /esemenyek/ stb.) — célzottan a 'programok' aldomain alatti link.
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # Csak a saját domain és egyedi program oldal
            if "zalaegerszegturizmus.hu" not in href and not href.startswith("/"):
                continue
            # Cél: konkrét esemény oldal — több path elem után -al-detail
            full = urljoin(EVENTS_URL, href)
            parsed = urlparse(full)
            if parsed.netloc != "zalaegerszegturizmus.hu":
                continue
            # Kihagyjuk a generic /programok/ főoldalt, és a pageinátort
            path = parsed.path.rstrip("/")
            if path in ("/programok", "") or "/page/" in path or path.endswith("/programok"):
                continue
            # Csak ami /programok/<valami> vagy /esemenyek/<valami>
            if not (path.startswith("/programok/") or path.startswith("/esemenyek/")):
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 5:
                continue
            candidates.append((full, title))

        # Dedup + max
        seen = set()
        for url, title in candidates:
            if url in seen:
                continue
            seen.add(url)
            if len(items) >= max_items:
                break
            # Az URL alapján generáljuk az external_id-t (sha256[:32])
            ext_id = "event:" + hashlib.sha256(url.encode()).hexdigest()[:32]
            items.append({
                "external_id": ext_id,
                "source_url": url,
                "source_name": "zalaegerszegturizmus.hu",
                "title": title[:500],
            })
    except requests.RequestException:
        pass
    except Exception:
        pass
    return items


def fetch_event_detail(url: str) -> dict:
    """Egyetlen esemény részletes oldal scrape.
    Returns: {og_image, content (description), event_start_at, event_end_at, event_location}
    """
    out = {
        "og_image": None,
        "content": "",
        "event_start_at": None,
        "event_end_at": None,
        "event_location": "",
    }
    try:
        resp = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT)
        if not resp.ok:
            return out
        soup = BeautifulSoup(resp.text, "lxml")

        og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_img and og_img.get("content"):
            out["og_image"] = urljoin(resp.url, og_img["content"].strip())

        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            out["content"] = og_desc["content"].strip()

        # Article body
        article = soup.find("article") or soup.find("main") or soup
        for tag in article(["script", "style", "nav", "aside", "form", "iframe", "header", "footer"]):
            tag.decompose()
        body = article.get_text(" ", strip=True)
        body = re.sub(r"\s+", " ", body).strip()
        # Use OG description if found, else the body
        if not out["content"] and body:
            out["content"] = body[:4000]
        else:
            out["content"] = (out["content"] + " " + body)[:4000]

        # Próbáljuk megtalálni a dátumot — gyakran "2026. május 20" vagy hasonló
        date_match = re.search(
            r"(\d{4}\.?\s*(?:" + "|".join(HU_MONTH.keys()) + r")\s*\d{1,2})",
            body.lower(),
        )
        if date_match:
            out["event_start_at"] = _parse_hu_date(date_match.group(1))

        # Helyszín — egyszerű heurisztika: "Helyszín:" után az első szöveg
        loc_match = re.search(r"helyszín[:\s]+([^\.]{3,200})", body, re.IGNORECASE)
        if loc_match:
            out["event_location"] = loc_match.group(1).strip()[:300]
    except requests.RequestException:
        pass
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────────────
# Kép letöltés és thumbnail
# ─────────────────────────────────────────────────────────────────────

def download_image(url: str) -> str | None:
    """Letölt egy képet, thumbnailre szabja (max 800x800), WebP-ben menti
    a NEWS_IMAGE_DIR alá. Visszaad: relatív path (pl. 'news_images/abc.webp')
    vagy None ha sikertelen.
    """
    if not url:
        return None
    try:
        os.makedirs(NEWS_IMAGE_DIR, exist_ok=True)
    except OSError:
        return None

    try:
        resp = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, stream=True)
        if not resp.ok or not resp.content:
            return None
        # Max 8 MB — Pillow DecompressionBombError védelmen kívül még egy size guard
        if len(resp.content) > 8 * 1024 * 1024:
            return None

        img = Image.open(io.BytesIO(resp.content))
        img = img.convert("RGB")
        img.thumbnail((800, 800), Image.LANCZOS)

        filename = f"{uuid.uuid4().hex}.webp"
        safe_path = os.path.realpath(os.path.join(NEWS_IMAGE_DIR, filename))
        if not safe_path.startswith(os.path.realpath(NEWS_IMAGE_DIR) + os.sep):
            return None
        img.save(safe_path, format="WEBP", quality=78, method=4)
        return f"news_images/{filename}"
    except Image.DecompressionBombError:
        return None
    except (requests.RequestException, OSError, ValueError):
        return None
    except Exception:
        return None
