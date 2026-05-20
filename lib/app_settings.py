"""Admin-állítható konfigurációs paraméterek (nem titkosított).

Az `app_settings` DB tábla key-value pár-jaiba ír / olvas. Ellentétben a
`lib/secrets.py`-tól (titkosított), ez plain text — itt nincs érzékeny adat
(napi limit, idő-ablak, CTA variánsok stb.).

Use:
    from lib.app_settings import get_int_setting, set_setting
    max_per_day = get_int_setting("fb_autopost.max_per_day", default=8,
                                  env_fallback="FB_AUTOPOST_MAX_PER_DAY")
    set_setting("fb_autopost.max_per_day", "10", user_id=current_user.id)
"""

import json
import logging
import os
import time
from typing import Any, Optional

from lib.database import get_db

log = logging.getLogger(__name__)

# Modul-szintű cache, 60 mp TTL. Írás után automatikus invalidálás.
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 60.0


def get_setting(
    key: str, default: str = "", env_fallback: str = ""
) -> str:
    """Olvas egy beállítást a DB-ből (string).

    env_fallback: ha a DB-ben nincs, a megadott környezeti változót próbáljuk.
    default: ha sem DB, sem env nincs.
    """
    now = time.time()
    if key in _cache:
        value, expires = _cache[key]
        if now < expires:
            return value
        _cache.pop(key, None)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = %s", (key,)
        ).fetchone()
        if row:
            value = row["value"]
            _cache[key] = (value, now + _CACHE_TTL)
            return value
    except Exception as e:
        log.error(f"[app_settings] DB read error key={key}: {e}")
    finally:
        conn.close()

    if env_fallback:
        env_val = os.getenv(env_fallback, "").strip()
        if env_val:
            return env_val

    return default


def get_int_setting(
    key: str, default: int = 0, env_fallback: str = ""
) -> int:
    """Int-típusú beállítás. Nem-int érték esetén default-ra esik vissza."""
    raw = get_setting(key, env_fallback=env_fallback)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_bool_setting(
    key: str, default: bool = False, env_fallback: str = ""
) -> bool:
    """Bool-típusú beállítás. true / 1 / yes / on → True, minden más → False."""
    raw = get_setting(key, env_fallback=env_fallback).strip().lower()
    if not raw:
        return default
    return raw in ("true", "1", "yes", "on")


def get_json_setting(key: str, default: Any = None) -> Any:
    """JSON-szerializált beállítás (pl. lista, dict)."""
    raw = get_setting(key, default="")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def set_setting(
    key: str, value: str, user_id: Optional[int] = None
) -> bool:
    """Beállítás mentése (vagy frissítése). Üres value → DELETE."""
    if value is None or value == "":
        return delete_setting(key)

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at, updated_by)
               VALUES (%s, %s, NOW(), %s)
               ON CONFLICT (key) DO UPDATE SET
                   value = EXCLUDED.value,
                   updated_at = NOW(),
                   updated_by = EXCLUDED.updated_by""",
            (key, str(value), user_id),
        )
        conn.commit()
        _cache[key] = (str(value), time.time() + _CACHE_TTL)
        return True
    except Exception as e:
        log.error(f"[app_settings] Write error key={key}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def set_int_setting(
    key: str, value: int, user_id: Optional[int] = None
) -> bool:
    return set_setting(key, str(int(value)), user_id)


def set_bool_setting(
    key: str, value: bool, user_id: Optional[int] = None
) -> bool:
    return set_setting(key, "true" if value else "false", user_id)


def set_json_setting(
    key: str, value: Any, user_id: Optional[int] = None
) -> bool:
    return set_setting(key, json.dumps(value, ensure_ascii=False), user_id)


def delete_setting(key: str) -> bool:
    conn = get_db()
    try:
        conn.execute("DELETE FROM app_settings WHERE key = %s", (key,))
        conn.commit()
        _cache.pop(key, None)
        return True
    except Exception as e:
        log.error(f"[app_settings] Delete error key={key}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def invalidate_cache(key: Optional[str] = None) -> None:
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)
