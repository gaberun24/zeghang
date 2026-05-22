#!/usr/bin/env python3
"""
Hír- és program-aggregátor CLI script.
Cron: */30 * * * * /opt/zeghang/venv/bin/python /opt/zeghang/fetch_news.py >> /opt/zeghang/news.log 2>&1

Mit csinál:
1. Google News RSS lekérés (helyi + megyei) → új cikk dedup → forrás-cikk fetch
   → OG image → AI summary → DB INSERT
2. zalaegerszegturizmus.hu/programok scrape → új program dedup → részletes
   fetch → AI ajánló → DB INSERT
3. 90 napnál régebbi hírek (kivéve programok) törlése

Idempotens: dedup az external_id UNIQUE constraint-en.
"""

import logging
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

# Repo gyökeret a path-ba
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.database import get_db, init_db
from lib.ai import summarize_news, summarize_event
from lib.news_fetcher import (
    fetch_google_news,
    fetch_direct_rss,
    DIRECT_RSS_SOURCES,
    resolve_real_url,
    fetch_article_content,
    fetch_events,
    fetch_event_detail,
    download_image,
    normalize_url,
    title_hash,
    parse_event_date,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# Zaj-szűrő: ezek nem hírek, kiszűrve a Google News dump-ból.
# (idokep = időjárás, listing.hu = hirdetés, stb.)
SOURCE_BLACKLIST_PATTERNS = [
    "idokep.hu",
    "meteoblue",
    "weatheronline",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
]


def _is_noise(url: str, title: str) -> bool:
    """Megnézi, hogy a cikk zaj-forrásból jön-e (időjárás, social, stb.)."""
    if not url:
        return False
    url_l = url.lower()
    if any(p in url_l for p in SOURCE_BLACKLIST_PATTERNS):
        return True
    return False


# A helyi (category='local') relevancia-szűréshez: ezek bármelyikének
# benne kell lenni a TITLE-ben vagy az URL-ben.
# (A "zalaegerszeg" tartalmazza a "zalaegerszegi" formát is.)
ZEG_RELEVANCE_TOKENS = (
    "zalaegerszeg",  # lefedi "zalaegerszegi", "Zalaegerszegen" stb.
    "egerszeg",      # lefedi "egerszegi", "Egerszegi"
)

# Zala megyei (category='county') relevancia: Zala megyei városok/települések
# vagy "zala" prefix. A ZAOL aggregator néha országos/külföldi hírt is bedob —
# ezek nem érdekesek a megyei oldalon ("Dnyipró dróncsapás", "Eurós nyugdíj" stb.).
ZALA_RELEVANCE_TOKENS = (
    "zala",         # zalai, Zalaegerszeg, Zalakaros, Zalaszentgrót, Zalalövő, Zalában stb.
    "egerszeg",     # Zalaegerszeg → már fent, de itt is biztosra megy
    "lenti",
    "nagykanizsa", "kanizsa",
    "keszthely",
    "hévíz", "heviz",
    "letenye",
    "pacsa",
    "söjtör", "sojtor",
    "becsehely",
    "gellénháza", "gellenhaza",
    "alibánfa",
    "zalakaros",
    "lispeszentadorján",
    "csesztreg",
    "göcsej",       # földrajzi régió Zalában
)


def _is_zeg_relevant(title: str, source_name: str, source_url: str) -> bool:
    """True ha a cikk valószínűleg ZALAEGERSZEGI helyi vonatkozású.

    A Google News q=zalaegerszeg túl megengedő — visszaadhat olyan cikket
    is, ami csak egy mellékmondatban említi a várost (pl. Fradi Shop
    "zalaegerszegi üzlete" → NEM helyi hír). Ezért követelünk min. egy
    token-match-et a TITLE vagy az URL-ben.

    FIGYELEM: a source_name szándékosan KIHAGYVA — a "ZAOL" source-name
    tartalmazná a "zaol" tokent, és minden ZAOL cikket ZEG-relevánsnak
    minősítene (még a Lenti/Nagykanizsa megyei cikkeket is). A title +
    URL pontos jelzés.

    Példák:
      "Új körforgalom a Balatoni úton, Zalaegerszegen" → ✓ (title)
      "Hatalmas fogás Zalában, sormási pihenő..." → ✗ (csak megyei,
        a ZAOL fallback_category=county-ba menti)
      "Pünkösdkor zárva tart a Fradi Shop" → ✗
    """
    haystack = " ".join([
        (title or "").lower(),
        (source_url or "").lower(),
    ])
    return any(tok in haystack for tok in ZEG_RELEVANCE_TOKENS)


def _is_zala_relevant(title: str, source_url: str) -> bool:
    """True ha a cikk Zala-megyei vonatkozású.

    A ZAOL aggregator (Hirstart) néha országos/külföldi cikket is bedob a
    feedjébe (pl. "Dnyipró dróncsapás", "Eurós nyugdíj Magyarországon",
    "YouTube új rendszert vezet be"). Ezek a megyei oldalon zajnak számítanak.

    Példák:
      "Hatalmas fogás Zalában, sormási pihenő" → ✓ (zala)
      "Söjtörön filmforgatás" → ✓ (söjtör)
      "Nagykanizsa csapatkapitány" → ✓ (nagykanizsa)
      "Dnyipró dróncsapás" → ✗ (semmi)
      "Eurós nyugdíj Magyarországon" → ✗ (országos)
    """
    haystack = " ".join([
        (title or "").lower(),
        (source_url or "").lower(),
    ])
    return any(tok in haystack for tok in ZALA_RELEVANCE_TOKENS)


def _clean_title(raw: str) -> str:
    """Title-prefix tisztítás: 'Hírarchívum - ', 'Archív - ', 'Vélemény - ', stb."""
    if not raw:
        return raw
    prefixes = [
        r"^h[ií]rarch[ií]vum\s*[\-–:]\s*",
        r"^arch[ií]v\s*[\-–:]\s*",
        r"^v[eé]lem[eé]ny\s*[\-–:]\s*",
        r"^sport\s*[\-–:]\s*",
    ]
    cleaned = raw
    for p in prefixes:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")[:120]
    except Exception:
        return ""


def _exists_by_external_id(conn, external_id: str) -> bool:
    """1. szintű dedup: pontos Google guid / event hash egyezés."""
    row = conn.execute(
        "SELECT 1 FROM news_items WHERE external_id = %s",
        (external_id,),
    ).fetchone()
    return bool(row)


def _exists_by_url(conn, normalized: str) -> bool:
    """2. szintű dedup: ugyanaz a kanonizált forrás-URL (tracking-paraméterek
    nélkül). Ez fogja meg az utm-paraméteres + reposztolt duplikátumokat."""
    if not normalized:
        return False
    row = conn.execute(
        "SELECT 1 FROM news_items WHERE normalized_url = %s",
        (normalized,),
    ).fetchone()
    return bool(row)


def _exists_by_title_recent(conn, t_hash: str, days: int = 14) -> bool:
    """3. szintű dedup: ugyanaz a cím-hash az utolsó N napban — fogja meg az
    MTI-alapú cikkeket amit több portál is leadott."""
    if not t_hash:
        return False
    row = conn.execute(
        """SELECT 1 FROM news_items
           WHERE title_hash = %s
             AND fetched_at >= NOW() - INTERVAL '%s days'""",
        (t_hash, days),
    ).fetchone()
    return bool(row)


def _is_duplicate(conn, external_id: str, normalized_url: str, t_hash: str) -> tuple[bool, str]:
    """Triple-check dedup. Returns (is_dup, reason)."""
    if _exists_by_external_id(conn, external_id):
        return True, "guid"
    if _exists_by_url(conn, normalized_url):
        return True, "url"
    if _exists_by_title_recent(conn, t_hash):
        return True, "title"
    return False, ""


def process_news(category: str) -> int:
    """Helyi vagy megyei hírek beolvasása. Returns: új cikkek száma."""
    log.info(f"[{category}] Google News RSS lekérés…")
    items = fetch_google_news(category)
    log.info(f"[{category}] {len(items)} item az RSS-ben")

    inserted = 0
    skipped = {"guid": 0, "url": 0, "title": 0}
    conn = get_db()
    try:
        for item in items:
            # 1. szintű dedup: pontos guid match (gyors, fetch nélkül)
            if _exists_by_external_id(conn, item["external_id"]):
                skipped["guid"] += 1
                continue

            # 2. szintű előzetes title-hash check — még a HTTP fetch ELŐTT, költség-spórolás
            t_hash = title_hash(item["title"])
            if _exists_by_title_recent(conn, t_hash):
                skipped["title"] += 1
                continue

            # Resolve a real source URL — Google News base64 payload dekódolás.
            # Ha nem oldódik fel, skip — Google URL-jén úgysem találunk OG image-et.
            real_url = resolve_real_url(item["source_url"])
            if not real_url:
                log.warning(f"[{category}] URL nem feloldható, skip: {item['title'][:50]}")
                continue

            # Zaj-szűrő: időjárás-oldalak, social, stb.
            if _is_noise(real_url, item["title"]):
                log.info(f"[{category}] zaj-forrás, skip: {real_url[:60]}")
                continue

            # Helyi-relevancia szűrő: ha a category='local', követeljük meg
            # hogy a title/URL/source-name tartalmazza valamelyik zeg-tokent.
            # Cél: kiszűrni a Google News false-positive találatokat (pl. Fradi Shop
            # cikk, ami csak egy mondatban említi Zalaegerszeget).
            if category == "local":
                src_name = item.get("source_name") or _domain(real_url)
                if not _is_zeg_relevant(item["title"], src_name, real_url):
                    log.info(
                        f"[{category}] nem ZEG-releváns ({src_name}), skip: "
                        f"{item['title'][:60]}"
                    )
                    continue

            # Megyei relevancia: a Google News q=zala+megye-feed-ből csak Zala-
            # releváns cikkeket fogadunk el. A feed sokszor országos hírt is bedob
            # (pl. Fradi-cikkek, országos szabályozás), ezeket szűrjük.
            if category == "county":
                if not _is_zala_relevant(item["title"], real_url):
                    log.info(
                        f"[{category}] nem Zala-releváns, skip: {item['title'][:60]}"
                    )
                    continue

            norm_url = normalize_url(real_url)

            # 3. szintű URL-dedup — most már a kanonizált URL ismeretében
            if _exists_by_url(conn, norm_url):
                skipped["url"] += 1
                continue

            article = fetch_article_content(real_url)
            # Frissítsük a normalized_url-t a fetch utáni végleges URL-lel
            final_url = article.get("real_url") or real_url
            norm_url = normalize_url(final_url)
            # És még egy ellenőrzés — egy redirect ide vezethetett egy már beillesztett cikkre
            if _exists_by_url(conn, norm_url):
                skipped["url"] += 1
                continue

            # Source name: priorizáljuk az RSS-ből kapottat, ha nincs, domain
            source_name = item["source_name"] or _domain(final_url)

            # Skip a direkt RSS-eken keresztül kapott forrásokat — onnan
            # snippet + image jön teljes adattal. A Google News-on át ezek
            # Cloudflare-blokkba esnek (NO_IMG/NO_SUM), és blokkolnák a
            # direkt RSS-flow-t az URL-dedup miatt.
            direct_rss_sources = {src["source_name"] for src in DIRECT_RSS_SOURCES}
            if source_name in direct_rss_sources:
                log.info(
                    f"[{category}] direkt RSS-en jön: skip Google News-on át "
                    f"({source_name}): {item['title'][:50]}"
                )
                continue

            # Title clean (Hírarchívum-prefix, stb.)
            clean_title = _clean_title(item["title"])

            # AI summary + importance
            content = article.get("content") or article.get("og_description") or ""
            if content:
                ai_summary, importance = summarize_news(clean_title, content)
            else:
                ai_summary, importance = None, 1

            # Image — referer = a forrás cikk URL-je (hotlink protection-bypass)
            image_local = (
                download_image(article.get("og_image"), referer=final_url)
                if article.get("og_image") else None
            )

            try:
                conn.execute(
                    """
                    INSERT INTO news_items
                      (category, external_id, source_url, source_name, title,
                       title_hash, normalized_url,
                       ai_summary, image_url, image_local_path, published_at,
                       importance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (
                        category,
                        item["external_id"],
                        final_url,
                        source_name,
                        clean_title,
                        t_hash,
                        norm_url,
                        ai_summary,
                        article.get("og_image"),
                        image_local,
                        item["published_at"],
                        importance,
                    ),
                )
                conn.commit()
                inserted += 1
                imp_marker = "📌📌📌"[:importance] if importance > 1 else ""
                log.info(f"[{category}] + {imp_marker}{item['title'][:80]}")
            except Exception as e:
                conn.rollback()
                log.warning(f"[{category}] INSERT failed: {e}")
    finally:
        conn.close()

    log.info(
        f"[{category}] {inserted} új · skip: guid={skipped['guid']} "
        f"url={skipped['url']} title={skipped['title']}"
    )
    return inserted


def process_direct_rss(
    rss_url: str, category: str, source_name: str,
    allowed_categories: list[str] | None = None,
    fallback_category: str | None = None,
) -> int:
    """Direkt portál-RSS feldolgozása (Cloudflare-megkerülés).

    A Google News-flow-tól eltérően:
    - source_url már a valódi cikk URL-je (nem Google redirect)
    - description (snippet) az AI summary forrása (nincs HTML-content-fetch)
    - enclosure_url a kép URL — közvetlenül letöltjük (referer = a cikk URL-je)

    allowed_categories: ha be van állítva, csak azokat az item-eket fogadjuk
    el, amik <category> tagjében szerepel valamelyik elem. Pl. Egerszegi Hírek-
    nél `["Helyi hírek"]` → a "Light" rovat országos cikkei kiesnek.

    fallback_category: ha a forrás dual-purpose (pl. ZAOL = ZEG + Zala megye),
    akkor a non-ZEG cikkek ide kerülnek a primary `category` helyett. Pl. ZAOL
    forrásnál category='local', fallback_category='county' → a Lenti/Nagykanizsa
    cikkek 'county'-ba mennek a 'local' helyett.

    Dedup + relevancia-szűrő + noise-szűrő ugyanúgy alkalmazzuk.
    """
    log.info(f"[direct:{source_name}] RSS lekérés…")
    items = fetch_direct_rss(rss_url, category, source_name)
    log.info(f"[direct:{source_name}] {len(items)} item az RSS-ben")

    inserted = 0
    counts_per_cat = {category: 0}
    if fallback_category:
        counts_per_cat[fallback_category] = 0
    skipped = {"guid": 0, "url": 0, "title": 0, "noise": 0, "irrelevant": 0, "no_content": 0, "category": 0}
    conn = get_db()
    try:
        for item in items:
            # 0. kategória-szűrő (ha be van állítva forrás-szinten)
            if allowed_categories:
                item_tags = item.get("tags") or []
                if not any(t in allowed_categories for t in item_tags):
                    skipped["category"] += 1
                    log.info(
                        f"[direct:{source_name}] kategória ({item_tags}) "
                        f"nincs az engedélyezettek között, skip: {item['title'][:60]}"
                    )
                    continue

            # 1. guid dedup
            if _exists_by_external_id(conn, item["external_id"]):
                skipped["guid"] += 1
                continue

            # 2. előzetes title-hash dedup
            t_hash = title_hash(item["title"])
            if _exists_by_title_recent(conn, t_hash):
                skipped["title"] += 1
                continue

            real_url = item["source_url"]

            # 3. noise-szűrő (csak URL alapján — title-t direkt RSS-ben már látjuk)
            if _is_noise(real_url, item["title"]):
                skipped["noise"] += 1
                log.info(f"[direct:{source_name}] zaj-forrás, skip: {real_url[:60]}")
                continue

            # 4. ZEG-relevancia-szűrő — meghatározzuk az effective_category-t
            # ZEG-releváns → primary category (local). Non-ZEG: ha van fallback,
            # de Zala-releváns → fallback (county). Külföldi/országos → skip.
            effective_category = category
            if category == "local":
                if not _is_zeg_relevant(item["title"], source_name, real_url):
                    if fallback_category == "county":
                        # County-ba csak Zala-releváns mehet, különben skip
                        if not _is_zala_relevant(item["title"], real_url):
                            skipped["irrelevant"] += 1
                            log.info(
                                f"[direct:{source_name}] nem Zala-releváns "
                                f"(külföldi/országos), skip: {item['title'][:60]}"
                            )
                            continue
                        effective_category = fallback_category
                        log.info(
                            f"[direct:{source_name}] non-ZEG → county: "
                            f"{item['title'][:60]}"
                        )
                    elif fallback_category:
                        effective_category = fallback_category
                        log.info(
                            f"[direct:{source_name}] non-ZEG → {fallback_category}: "
                            f"{item['title'][:60]}"
                        )
                    else:
                        skipped["irrelevant"] += 1
                        log.info(
                            f"[direct:{source_name}] nem ZEG-releváns, skip: "
                            f"{item['title'][:60]}"
                        )
                        continue

            # 5. URL-dedup (normalizált)
            norm_url = normalize_url(real_url)
            if _exists_by_url(conn, norm_url):
                skipped["url"] += 1
                continue

            # Title clean
            clean_title = _clean_title(item["title"])

            # AI summary + importance a snippet-ből
            content = item.get("description") or ""
            if not content:
                skipped["no_content"] += 1
                log.info(
                    f"[direct:{source_name}] üres snippet, skip: {clean_title[:60]}"
                )
                continue
            ai_summary, importance = summarize_news(clean_title, content)

            # Kép letöltés az enclosure-ből (referer = a cikk URL-je)
            image_local = None
            if item.get("enclosure_url"):
                image_local = download_image(
                    item["enclosure_url"], referer=real_url
                )

            try:
                conn.execute(
                    """
                    INSERT INTO news_items
                      (category, external_id, source_url, source_name, title,
                       title_hash, normalized_url,
                       ai_summary, image_url, image_local_path, published_at,
                       importance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (
                        effective_category,
                        item["external_id"],
                        real_url,
                        source_name,
                        clean_title,
                        t_hash,
                        norm_url,
                        ai_summary,
                        item.get("enclosure_url"),
                        image_local,
                        item["published_at"],
                        importance,
                    ),
                )
                conn.commit()
                inserted += 1
                counts_per_cat[effective_category] = counts_per_cat.get(effective_category, 0) + 1
                imp_marker = "📌📌📌"[:importance] if importance > 1 else ""
                log.info(
                    f"[direct:{source_name}/{effective_category}] + {imp_marker}{clean_title[:80]}"
                )
            except Exception as e:
                conn.rollback()
                log.warning(f"[direct:{source_name}] INSERT failed: {e}")
    finally:
        conn.close()

    cat_breakdown = ", ".join(f"{cat}={cnt}" for cat, cnt in counts_per_cat.items() if cnt > 0) or "0"
    log.info(
        f"[direct:{source_name}] {inserted} új ({cat_breakdown}) · skip: "
        f"guid={skipped['guid']} url={skipped['url']} title={skipped['title']} "
        f"noise={skipped['noise']} irrelevant={skipped['irrelevant']} "
        f"no_content={skipped['no_content']} category={skipped['category']}"
    )
    return inserted


def process_events() -> int:
    """Zalaegerszegturizmus.hu programok. Returns: új események száma."""
    log.info("[events] zalaegerszegturizmus.hu/programok scrape…")
    items = fetch_events()
    log.info(f"[events] {len(items)} esemény a listán")

    inserted = 0
    skipped = {"guid": 0, "url": 0, "title": 0}
    conn = get_db()
    try:
        for item in items:
            if _exists_by_external_id(conn, item["external_id"]):
                skipped["guid"] += 1
                continue

            norm_url = normalize_url(item["source_url"])
            if _exists_by_url(conn, norm_url):
                skipped["url"] += 1
                continue

            t_hash = title_hash(item["title"])
            # Eseményeknél hosszabb dedup-ablak — 60 nap, mert ugyanaz a koncert
            # több hónapig lehet a listán (ismétlések)
            if _exists_by_title_recent(conn, t_hash, days=60):
                skipped["title"] += 1
                continue

            detail = fetch_event_detail(item["source_url"])
            # A listanézet title-jében benne van a dátum elöl (pl.
            # "május 30 2026 Disco dívák") — ez megbízhatóbb mint a body-ban
            # talált első dátum, mert az gyakran a lábléc "1848. március 15"
            # emlékszövegét fogja meg.
            list_date = parse_event_date(item["title"]) if item.get("title") else None
            final_start_at = list_date or detail.get("event_start_at")

            # Tisztább title a részletes oldalról (og:title vagy h1), ha létezik.
            # A listanézet a dátumot is belerakja a link szövegébe — azt nem akarjuk.
            final_title = (detail.get("og_title") or item["title"]).strip()
            # title_hash újraszámolás — már a tiszta címmel
            t_hash = title_hash(final_title)
            content = detail.get("content") or ""
            ai_summary = summarize_event(final_title, content) if content else None
            image_local = (
                download_image(detail.get("og_image"), referer=item["source_url"])
                if detail.get("og_image") else None
            )

            try:
                conn.execute(
                    """
                    INSERT INTO news_items
                      (category, external_id, source_url, source_name, title,
                       title_hash, normalized_url,
                       ai_summary, image_url, image_local_path,
                       event_start_at, event_end_at, event_location)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (
                        "event",
                        item["external_id"],
                        item["source_url"],
                        item["source_name"],
                        final_title,
                        t_hash,
                        norm_url,
                        ai_summary,
                        detail.get("og_image"),
                        image_local,
                        final_start_at,
                        detail.get("event_end_at"),
                        detail.get("event_location"),
                    ),
                )
                conn.commit()
                inserted += 1
                date_str = final_start_at.strftime("%Y-%m-%d") if final_start_at else "?"
                log.info(f"[events] + ({date_str}) {final_title[:60]}")
            except Exception as e:
                conn.rollback()
                log.warning(f"[events] INSERT failed: {e}")
    finally:
        conn.close()

    log.info(
        f"[events] {inserted} új · skip: guid={skipped['guid']} "
        f"url={skipped['url']} title={skipped['title']}"
    )
    return inserted


def purge_old(days: int = 90) -> int:
    """90+ napos hírek törlése (programokat nem érinti, mert event_start_at alapján
    a múltbeli eseményeket az UI úgyis kiszűri)."""
    conn = get_db()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        result = conn.execute(
            """DELETE FROM news_items
               WHERE category IN ('local', 'county')
                 AND COALESCE(published_at, fetched_at) < %s
               RETURNING id""",
            (cutoff,),
        )
        try:
            rows = result.fetchall()
            count = len(rows)
        except Exception:
            count = 0
        conn.commit()
        log.info(f"[purge] {count} régi hír törölve (>{days} nap)")
        return count
    except Exception as e:
        conn.rollback()
        log.warning(f"[purge] failed: {e}")
        return 0
    finally:
        conn.close()


def main():
    """CSAK helyi és megyei hírek (Google News). Az események külön scriptből
    futnak naponta 1x (fetch_events.py)."""
    try:
        init_db()
    except Exception as e:
        log.warning(f"init_db: {e}")

    total = 0
    total += process_news("local")
    total += process_news("county")

    # Direkt portál-RSS-ek (Cloudflare-megkerülés a Mediaworks-féle portálokhoz,
    # és az Egerszegi Hírek + zalaegerszeg.hu kategória-szűrőkkel).
    # ZAOL dual-purpose: ZEG-releváns→local, többi→county.
    for src in DIRECT_RSS_SOURCES:
        try:
            total += process_direct_rss(
                src["url"], src["category"], src["source_name"],
                allowed_categories=src.get("allowed_categories"),
                fallback_category=src.get("fallback_category"),
            )
        except Exception as e:
            log.warning(f"[direct:{src['source_name']}] feldolgozási hiba: {e}")

    # Auto-cleanup: hiányos (NO_IMG VAGY NO_SUM) cikkek törlése amik már 1+ órája
    # bent vannak. Ezek főleg a Google News-on át kapott Cloudflare-blokkos
    # ZAOL cikkek — a direkt RSS-flow majd újra-fetcheli őket képpel + summary-val.
    cleanup_incomplete(min_age_hours=1)

    purge_old(90)
    log.info(f"[done] {total} új hír")


def cleanup_incomplete(min_age_hours: int = 1) -> None:
    """Hiányos (NO_IMG VAGY NO_SUM) unposted cikkek törlése amik már min_age_hours+
    órája bent vannak — addigra ha a direkt RSS-flow tudta volna fetchelni, megtette.
    """
    conn = get_db()
    try:
        r = conn.execute(
            f"""DELETE FROM news_items
                WHERE fb_posted_at IS NULL
                  AND fetched_at < NOW() - INTERVAL '{min_age_hours} hours'
                  AND (image_local_path IS NULL OR ai_summary IS NULL)
                RETURNING id, category, source_name"""
        ).fetchall()
        conn.commit()
        if r:
            from collections import Counter
            by_cat = Counter(row["category"] for row in r)
            by_src = Counter(row["source_name"] for row in r if row["source_name"])
            log.info(
                f"[cleanup] {len(r)} hiányos cikk törölve (kat: "
                f"{dict(by_cat)}, top forrás: {by_src.most_common(3)})"
            )
    except Exception as e:
        log.warning(f"[cleanup] hiba: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


if __name__ == "__main__":
    main()
