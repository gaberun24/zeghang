"""Titkosított secret-tár (Fernet, DB-ben).

Cél: a .env-ből kiváltani a futás közben módosítandó secret-eket (FB token,
később OpenAI/Brevo kulcsok), így admin felületen át beállíthatók legyenek,
és titkosítva tárolódjanak a DB-ben.

A titkosítási kulcs:
- preferált: SETTINGS_ENCRYPTION_KEY env (Fernet-formátum, 44-char base64)
- fallback: FLASK_SECRET_KEY-ből PBKDF2-HMAC-SHA256 (100k iter, stabil salt)
  → ezzel a FLASK_SECRET_KEY rotáció felülírja az olvashatóságot, de a setup
  nulla extra env változót igényel.

Use:
    from lib.secrets import get_secret, set_secret, delete_secret
    page_id = get_secret("facebook.page_id", env_fallback="FACEBOOK_PAGE_ID")
    set_secret("facebook.page_id", "1031...", user_id=current_user.id)
"""

import base64
import hashlib
import logging
import os
import time
from typing import Optional

from lib.config import FLASK_SECRET_KEY
from lib.database import get_db

log = logging.getLogger(__name__)

# Lazy import — ha még nincs telepítve a cryptography, az app modul-loadig ne haljon.
try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_AVAILABLE = True
except ImportError:
    Fernet = None
    InvalidToken = Exception
    _CRYPTO_AVAILABLE = False
    log.warning("[secrets] cryptography lib missing — get_secret() csak env-fallback módban működik")

# Modul-szintű cache: 60 mp TTL. Secret írásnál invalidate_cache() törli.
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 60.0

_fernet_instance: Optional["Fernet"] = None


def _derive_fernet_key() -> bytes:
    """Fernet kompatibilis 32-byte base64 kulcs előállítása."""
    explicit = os.getenv("SETTINGS_ENCRYPTION_KEY", "").strip()
    if explicit:
        try:
            Fernet(explicit.encode())  # validáció
            return explicit.encode()
        except Exception as e:
            raise RuntimeError(
                "SETTINGS_ENCRYPTION_KEY hibás Fernet-formátum. "
                "Generálás: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ) from e

    # Fallback: derive from FLASK_SECRET_KEY (PBKDF2)
    salt = b"zeghang-secrets-v1"
    kdf = hashlib.pbkdf2_hmac("sha256", FLASK_SECRET_KEY.encode(), salt, 100_000)
    return base64.urlsafe_b64encode(kdf)


def _get_fernet() -> "Fernet":
    global _fernet_instance
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError(
            "cryptography lib nincs telepítve — pip install -r requirements.txt"
        )
    if _fernet_instance is None:
        _fernet_instance = Fernet(_derive_fernet_key())
    return _fernet_instance


def get_secret(key: str, default: str = "", env_fallback: str = "") -> str:
    """Olvas egy secret-et a DB-ből (dekódolva), cache-elve.

    env_fallback: ha a DB-ben üres a kulcs és cryptography sem elérhető,
    ezt a környezeti változót próbáljuk (.env kompatibilitás).
    """
    now = time.time()
    if key in _cache:
        value, expires = _cache[key]
        if now < expires:
            return value
        # lejárt — töröljük
        _cache.pop(key, None)

    # DB lookup
    if _CRYPTO_AVAILABLE:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT value_encrypted FROM app_secrets WHERE key = %s",
                (key,),
            ).fetchone()
            if row:
                try:
                    value = _get_fernet().decrypt(row["value_encrypted"].encode()).decode()
                    _cache[key] = (value, now + _CACHE_TTL)
                    return value
                except InvalidToken:
                    log.error(
                        f"[secrets] InvalidToken key={key} — "
                        "SETTINGS_ENCRYPTION_KEY / FLASK_SECRET_KEY változott?"
                    )
                    # Ne cache-eljük, próbáljuk az env fallback-et
        except Exception as e:
            log.error(f"[secrets] DB read error key={key}: {e}")
        finally:
            conn.close()

    # Env fallback (kompatibilitás)
    if env_fallback:
        env_val = os.getenv(env_fallback, "").strip()
        if env_val:
            return env_val

    return default


def set_secret(key: str, value: str, user_id: Optional[int] = None) -> bool:
    """Eltárol egy secret-et a DB-ben, Fernet-tel titkosítva.

    Üres value → törlés (delete_secret-tel).
    Returns: True sikernél.
    """
    if not value:
        return delete_secret(key)

    encrypted = _get_fernet().encrypt(value.encode()).decode()
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO app_secrets (key, value_encrypted, updated_at, updated_by)
               VALUES (%s, %s, NOW(), %s)
               ON CONFLICT (key) DO UPDATE SET
                   value_encrypted = EXCLUDED.value_encrypted,
                   updated_at = NOW(),
                   updated_by = EXCLUDED.updated_by""",
            (key, encrypted, user_id),
        )
        conn.commit()
        _cache[key] = (value, time.time() + _CACHE_TTL)
        return True
    except Exception as e:
        log.error(f"[secrets] Write error key={key}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def delete_secret(key: str) -> bool:
    conn = get_db()
    try:
        conn.execute("DELETE FROM app_secrets WHERE key = %s", (key,))
        conn.commit()
        _cache.pop(key, None)
        return True
    except Exception as e:
        log.error(f"[secrets] Delete error key={key}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def invalidate_cache(key: Optional[str] = None) -> None:
    """Modul cache törlése. key=None → mind."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


def get_secret_metadata(key: str) -> Optional[dict]:
    """Visszaadja a secret létezését + utolsó update info-t (nem dekódolja).

    Returns: {"updated_at": ..., "updated_by_email": ..., "preview": "...XXX"}
    Vagy None ha nem létezik a DB-ben.
    """
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT s.value_encrypted, s.updated_at, u.email AS updated_by_email
               FROM app_secrets s
               LEFT JOIN users u ON s.updated_by = u.id
               WHERE s.key = %s""",
            (key,),
        ).fetchone()
        if not row:
            return None

        preview = None
        if _CRYPTO_AVAILABLE:
            try:
                full = _get_fernet().decrypt(row["value_encrypted"].encode()).decode()
                preview = ("…" + full[-4:]) if len(full) > 8 else "(rövid)"
            except InvalidToken:
                preview = "(olvashatatlan)"

        return {
            "updated_at": row["updated_at"],
            "updated_by_email": row["updated_by_email"],
            "preview": preview,
        }
    finally:
        conn.close()
