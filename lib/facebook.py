"""
Facebook Page poszt-integráció Graph API-n keresztül.

A fb_autopost.py használja: 20 percenként új helyi hírt posztol a Page-re,
és a forrás-linket az 1. komment-be teszi (FB algoritmus link-penalty miatt).

Setup útmutató: README.md / "Facebook auto-poster setup" szekció.
Üres tokennel a függvények None-t adnak vissza (no-op).
"""

import logging
import os

import requests

from lib.config import FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN

log = logging.getLogger(__name__)

# Pinned API verzió — frissítéskor tudatosan léptessük át.
FB_API_VERSION = "v19.0"
FB_TIMEOUT = 15  # mp — multipart upload (kép) lassabb lehet


def _log_fb_error(context: str, resp: requests.Response | None, exc: Exception | None = None):
    """Részletes hibalog a debug-hoz — kiírja a FB API tényleges válaszát."""
    if exc:
        log.error(f"[fb-api] {context} exception: {exc}")
        return
    if resp is None:
        log.error(f"[fb-api] {context} (no response)")
        return
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500] if resp.text else "<empty>"
    log.error(f"[fb-api] {context} HTTP {resp.status_code}: {body}")


def _enabled() -> bool:
    """True, ha a Facebook integráció be van kapcsolva (van Page ID + token)."""
    return bool(FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN)


def post_photo_with_caption(message: str, image_local_abs_path: str) -> dict | None:
    """Képes poszt a Page-re. A 'message' a kép alá kerül, a kép maga a poszt fő tartalma.

    image_local_abs_path: a kép abszolút path-ja a fájlrendszerben (pl.
    /opt/zeghang/static/news_images/abc.webp).

    Returns: {"id": "<photo_id>", "post_id": "<page_id>_<post_id>"} sikernél,
             None hiba esetén (a hívó dönt mi legyen).
    """
    if not _enabled():
        return None
    if not os.path.isfile(image_local_abs_path):
        return None

    url = f"https://graph.facebook.com/{FB_API_VERSION}/{FACEBOOK_PAGE_ID}/photos"
    try:
        with open(image_local_abs_path, "rb") as img_file:
            files = {"source": img_file}
            data = {
                "message": message,
                "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
                # published=true → azonnal megjelenik
                "published": "true",
            }
            resp = requests.post(url, files=files, data=data, timeout=FB_TIMEOUT)
        if not resp.ok:
            _log_fb_error(f"post_photo_with_caption (img={image_local_abs_path})", resp)
            return None
        result = resp.json()
        # Sikeres válasz: {"id": "PHOTO_ID", "post_id": "PAGE_ID_POST_ID"}
        if not isinstance(result, dict) or "post_id" not in result:
            _log_fb_error("post_photo_with_caption (no post_id in response)", resp)
            return None
        return result
    except (requests.RequestException, OSError, ValueError) as e:
        _log_fb_error("post_photo_with_caption", None, e)
        return None
    except Exception as e:
        _log_fb_error("post_photo_with_caption (unexpected)", None, e)
        return None


def add_comment(post_id: str, message: str) -> str | None:
    """Komment hozzáadása egy poszthoz. post_id formátuma: PAGE_ID_POST_ID
    (a post_photo_with_caption visszaadott post_id-je).

    Returns: a komment ID-je sikernél, None hiba esetén.
    """
    if not _enabled() or not post_id or not message:
        return None

    url = f"https://graph.facebook.com/{FB_API_VERSION}/{post_id}/comments"
    try:
        resp = requests.post(
            url,
            data={"message": message, "access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
            timeout=FB_TIMEOUT,
        )
        if not resp.ok:
            _log_fb_error(f"add_comment (post={post_id})", resp)
            return None
        result = resp.json()
        if isinstance(result, dict) and "id" in result:
            return result["id"]
        _log_fb_error("add_comment (no id in response)", resp)
        return None
    except (requests.RequestException, ValueError) as e:
        _log_fb_error("add_comment", None, e)
        return None
    except Exception as e:
        _log_fb_error("add_comment (unexpected)", None, e)
        return None


def verify_token() -> dict | None:
    """Debug helper: ellenőrzi, hogy a Page Access Token még él-e.
    Returns: {"name": "Page neve", "id": "page_id"} ha OK, None ha hiba.
    """
    if not _enabled():
        return None
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me"
    try:
        resp = requests.get(
            url,
            params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
            timeout=FB_TIMEOUT,
        )
        if not resp.ok:
            return None
        return resp.json()
    except Exception:
        return None
