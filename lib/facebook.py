"""
Facebook Page poszt-integráció Graph API-n keresztül.

Token-tárolás: lib.secrets-en keresztül (DB-ben Fernet-titkosítva), .env fallback
kompatibilitás miatt. Az admin /admin/integraciok oldalon állítható minden.

Setup útmutató: README.md / "Facebook auto-poster setup" szekció.
Üres tokennel a függvények None-t adnak vissza (no-op).
"""

import logging
import os

import requests

from lib.secrets import get_secret

log = logging.getLogger(__name__)

# Pinned API verzió — frissítéskor tudatosan léptessük át.
FB_API_VERSION = "v19.0"
FB_TIMEOUT = 15  # mp — multipart upload (kép) lassabb lehet


# ─── Konfiguráció olvasás (DB → .env fallback) ─────────────────────────────

def get_page_id() -> str:
    """Aktuális Facebook Page ID, DB-ből, .env fallback-kel."""
    return get_secret("facebook.page_id", env_fallback="FACEBOOK_PAGE_ID")


def get_page_token() -> str:
    """Aktuális Page Access Token, DB-ből, .env fallback-kel."""
    return get_secret("facebook.page_access_token", env_fallback="FACEBOOK_PAGE_ACCESS_TOKEN")


def _enabled() -> bool:
    """True, ha a Facebook integráció be van kapcsolva (van Page ID + token)."""
    return bool(get_page_id() and get_page_token())


# ─── Hibalog helper ────────────────────────────────────────────────────────

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


# ─── Posztolás ─────────────────────────────────────────────────────────────

def post_photo_with_caption(message: str, image_local_abs_path: str) -> dict | None:
    """Képes poszt a Page-re. A 'message' a kép alá kerül, a kép maga a poszt fő tartalma.

    image_local_abs_path: a kép abszolút path-ja a fájlrendszerben (pl.
    /opt/zeghang/static/news_images/abc.webp).

    Returns: {"id": "<photo_id>", "post_id": "<page_id>_<post_id>"} sikernél,
             None hiba esetén (a hívó dönt mi legyen).
    """
    page_id = get_page_id()
    page_token = get_page_token()
    if not (page_id and page_token):
        return None
    if not os.path.isfile(image_local_abs_path):
        return None

    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/photos"
    try:
        with open(image_local_abs_path, "rb") as img_file:
            files = {"source": img_file}
            data = {
                "message": message,
                "access_token": page_token,
                # published=true → azonnal megjelenik
                "published": "true",
            }
            resp = requests.post(url, files=files, data=data, timeout=FB_TIMEOUT)
        if not resp.ok:
            _log_fb_error(f"post_photo_with_caption (img={image_local_abs_path})", resp)
            return None
        result = resp.json()
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
    page_token = get_page_token()
    if not page_token or not post_id or not message:
        return None

    url = f"https://graph.facebook.com/{FB_API_VERSION}/{post_id}/comments"
    try:
        resp = requests.post(
            url,
            data={"message": message, "access_token": page_token},
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
    """Debug helper: ellenőrzi, hogy az aktuális Page Access Token még él-e.

    Returns: {"name": "Page neve", "id": "page_id"} ha OK, None ha hiba.
    """
    page_token = get_page_token()
    if not page_token:
        return None
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me"
    try:
        resp = requests.get(
            url,
            params={"access_token": page_token},
            timeout=FB_TIMEOUT,
        )
        if not resp.ok:
            _log_fb_error("verify_token", resp)
            return None
        return resp.json()
    except Exception as e:
        _log_fb_error("verify_token", None, e)
        return None


# ─── OAuth helper-ek a long-lived flow-hoz (admin UI) ─────────────────────

def exchange_for_long_lived_user_token(
    short_user_token: str, app_id: str, app_secret: str
) -> dict | None:
    """Short-lived user token → long-lived user token (~60 nap).

    A long-lived user tokennel a /me/accounts-ból nyert page access token-ek
    "soha nem járnak le" (amíg a user nem revoke-ol / nem vált jelszót).

    Returns: {"access_token": "...", "token_type": "bearer", "expires_in": <sec>}
             None hiba esetén.
    """
    url = f"https://graph.facebook.com/{FB_API_VERSION}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_user_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=FB_TIMEOUT)
        if not resp.ok:
            _log_fb_error("exchange_for_long_lived_user_token", resp)
            return None
        return resp.json()
    except Exception as e:
        _log_fb_error("exchange_for_long_lived_user_token", None, e)
        return None


def list_pages(user_access_token: str) -> list[dict] | None:
    """Lekérdezi a user által kezelt Page-eket page access tokenekkel.

    Long-lived user tokennel hívva a kapott page access token-ek "never-expire"-ek.

    Returns: [{"id": "...", "name": "...", "access_token": "...", ...}, ...]
             None hiba esetén.
    """
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me/accounts"
    try:
        resp = requests.get(
            url, params={"access_token": user_access_token}, timeout=FB_TIMEOUT
        )
        if not resp.ok:
            _log_fb_error("list_pages", resp)
            return None
        body = resp.json()
        return body.get("data", [])
    except Exception as e:
        _log_fb_error("list_pages", None, e)
        return None


def get_token_debug_info(token: str) -> dict | None:
    """Megnézi a tokenről, hogy milyen típusú, kihez tartozik, mikor jár le.
    A Facebook Token Debugger lokál megfelelője.

    Returns a /debug_token endpoint válaszát ('data' belsejét).
    """
    url = f"https://graph.facebook.com/{FB_API_VERSION}/debug_token"
    # app access token kell ide: app_id|app_secret formában is megy
    # de egyszerűbb: input_token query, access_token ugyanaz
    try:
        resp = requests.get(
            url,
            params={"input_token": token, "access_token": token},
            timeout=FB_TIMEOUT,
        )
        if not resp.ok:
            _log_fb_error("get_token_debug_info", resp)
            return None
        body = resp.json()
        return body.get("data")
    except Exception as e:
        _log_fb_error("get_token_debug_info", None, e)
        return None
