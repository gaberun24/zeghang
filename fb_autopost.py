#!/usr/bin/env python3
"""
Facebook auto-poster cron script — 20 percenként fut, kiválaszt 1 friss helyi
hírt, AI teaser-rel kiposztolja a Page-re, a forrás-linket az 1. komment-be teszi.

Cron (20 percenként 07:00-22:40 között):
    */20 7-22 * * * /opt/zeghang/venv/bin/python /opt/zeghang/fb_autopost.py >> /opt/zeghang/fb_autopost.log 2>&1

Védelmi rétegek:
- Időablak check (Europe/Budapest 07:00-22:00)
- Napi limit (FB_AUTOPOST_MAX_PER_DAY, default 8)
- 60 perces ablak a kandidátok lekérésén (ha 1 cron-ciklus kihagy, a követő is futtat)
- Triple-check dedup már a fetch_news.py-ben, itt csak fb_posted_at IS NULL
- Üres token → no-op exit (a config.py guard-ja miatt)
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import (
    FB_AUTOPOST_MAX_PER_DAY,
    FB_CANDIDATE_WINDOW_MIN,
    SITE_URL,
)
from lib.database import get_db
from lib.ai import pick_interesting_article, generate_fb_teaser
from lib.facebook import (
    post_photo_with_caption,
    add_comment,
    get_page_id,
    get_page_token,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Europe/Budapest = UTC+1 (CET) vagy UTC+2 (CEST). Yhe egyszerű
# fix offset hamisítva lehet — a pythonban a zoneinfo a tisztább megoldás.
try:
    from zoneinfo import ZoneInfo
    BUDAPEST = ZoneInfo("Europe/Budapest")
except ImportError:  # pre-3.9 fallback (a venv-en 3.12 fut, ez nem fut le)
    BUDAPEST = timezone(timedelta(hours=2))

# Időablak: ezekben az órákban (helyi idő) megengedett a poszt.
ALLOWED_HOUR_MIN = 7
ALLOWED_HOUR_MAX = 22  # inclusive, azaz 22:00-22:59-ig megy

# Kandidatum-ablak a config-ból (FB_CANDIDATE_WINDOW_MIN env, default 360 = 6 óra)
CANDIDATE_WINDOW_MIN = FB_CANDIDATE_WINDOW_MIN

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(REPO_ROOT, "static")


def _log_event(event_type: str, details: str = "") -> None:
    """security_log-ba ír egy eseményt (FB poszt sikere/hibája)."""
    try:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO security_log (event_type, ip_address, details) "
                "VALUES (%s, %s, %s)",
                (event_type, "fb_autopost", details[:1000]),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # ne crasheljünk a logoláson


def _in_time_window() -> tuple[bool, str]:
    now_local = datetime.now(BUDAPEST)
    hour = now_local.hour
    ok = ALLOWED_HOUR_MIN <= hour <= ALLOWED_HOUR_MAX
    return ok, now_local.strftime("%H:%M")


def _today_post_count(conn) -> int:
    """Hány FB poszt ment ma (helyi idő szerint)."""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM news_items "
        "WHERE fb_posted_at::date = CURRENT_DATE"
    ).fetchone()
    return int(row["cnt"]) if row else 0


def _fetch_candidates(conn) -> list[dict]:
    """Helyi, friss, képes, AI-summary-vel rendelkező, még nem posztolt cikkek.

    Extra dedup: az utolsó 24 órában FB-re posztolt cikkek title_hash-eit
    kizárjuk → ha két kicsit más szöveggel jön ugyanaz a hír több portálról
    (a fetch-time title_hash csak EXACT match-et fog), itt is kiszűrjük.
    """
    rows = conn.execute(
        f"""SELECT id, title, ai_summary, source_name, source_url,
                   image_local_path, published_at, title_hash
            FROM news_items
            WHERE category = 'local'
              AND fb_posted_at IS NULL
              AND image_local_path IS NOT NULL
              AND ai_summary IS NOT NULL
              AND fetched_at >= NOW() - INTERVAL '{CANDIDATE_WINDOW_MIN} minutes'
              AND (
                title_hash IS NULL
                OR title_hash NOT IN (
                    SELECT title_hash FROM news_items
                    WHERE fb_posted_at >= NOW() - INTERVAL '24 hours'
                      AND title_hash IS NOT NULL
                )
              )
            ORDER BY COALESCE(published_at, fetched_at) DESC
            LIMIT 10"""
    ).fetchall()
    return [dict(r) for r in rows]


def _mark_posted(conn, item_id: int, fb_post_id: str) -> None:
    conn.execute(
        "UPDATE news_items SET fb_posted_at = NOW(), fb_post_id = %s WHERE id = %s",
        (fb_post_id, item_id),
    )
    conn.commit()


def main() -> int:
    log.info("=== fb_autopost.py indul ===")

    # 1. Konfiguráció check (DB → .env fallback)
    if not (get_page_id() and get_page_token()):
        log.info("[fb] Page ID vagy Access Token nincs beállítva "
                 "(admin /admin/integraciok vagy .env) — no-op")
        return 0

    # 2. Időablak
    in_window, hh_mm = _in_time_window()
    if not in_window:
        log.info(f"[fb] Időablak ({ALLOWED_HOUR_MIN:02d}:00-{ALLOWED_HOUR_MAX:02d}:59) "
                 f"kívül vagyunk ({hh_mm}) — exit")
        return 0
    log.info(f"[fb] Időablak: {hh_mm} ✓")

    conn = get_db()
    try:
        # 3. Napi limit
        today_count = _today_post_count(conn)
        if today_count >= FB_AUTOPOST_MAX_PER_DAY:
            log.info(f"[fb] Napi limit elérve: {today_count}/{FB_AUTOPOST_MAX_PER_DAY}")
            return 0
        log.info(f"[fb] Napi posztok: {today_count}/{FB_AUTOPOST_MAX_PER_DAY} ✓")

        # 4. Kandidatok
        candidates = _fetch_candidates(conn)
        log.info(f"[fb] {len(candidates)} kandidat")
        if not candidates:
            log.info("[fb] Nincs új helyi hír az utolsó 60 percben — semmit nem posztolunk")
            return 0

        # 5. AI pick (1 kandidatnál is OK — a function direkt visszaadja)
        chosen_id = pick_interesting_article(candidates)
        if not chosen_id:
            log.warning("[fb] AI pick nem adott vissza id-t")
            return 1
        chosen = next((c for c in candidates if c["id"] == chosen_id), None)
        if not chosen:
            log.warning(f"[fb] Választott id ({chosen_id}) nincs a kandidatok között")
            return 1
        log.info(f"[fb] AI pick: #{chosen_id} ({chosen['source_name']}: "
                 f"{chosen['title'][:60]})")

        # 6. AI teaser
        teaser = generate_fb_teaser(chosen["title"], chosen["ai_summary"])
        if not teaser:
            # Fallback: a meglévő ai_summary első 2 mondata
            sentences = chosen["ai_summary"].split(". ")
            teaser = ". ".join(sentences[:2]).strip()
            if not teaser.endswith("."):
                teaser += "."
        log.info(f"[fb] Teaser: {teaser[:100]}...")

        # 7. Kép abszolút path
        image_abs = os.path.realpath(os.path.join(STATIC_DIR, chosen["image_local_path"]))
        if not image_abs.startswith(os.path.realpath(STATIC_DIR) + os.sep):
            log.warning("[fb] Kép path traversal kísérlet — skip")
            return 1
        if not os.path.isfile(image_abs):
            log.warning(f"[fb] Kép fájl nem létezik: {image_abs}")
            return 1

        # 8. Posztolás
        post_result = post_photo_with_caption(teaser, image_abs)
        if not post_result or "post_id" not in post_result:
            _log_event("fb_post_failed", f"item={chosen_id} title={chosen['title'][:80]}")
            log.error(f"[fb] Posztolás kudarc — item #{chosen_id}")
            return 1
        post_id = post_result["post_id"]
        log.info(f"[fb] Posztolva: {post_id}")

        # 9. Komment a forrás-linkkel
        comment_body = f"📰 Eredeti cikk: {chosen['source_url']}\n\n🔗 További helyi hírek és bejelentés: {SITE_URL}/helyi-hirek"
        comment_id = add_comment(post_id, comment_body)
        if comment_id:
            log.info(f"[fb] Komment hozzáadva: {comment_id}")
        else:
            log.warning("[fb] Komment hozzáadás kudarc (de a poszt fent van)")

        # 10. DB jelölés
        _mark_posted(conn, chosen_id, post_id)
        _log_event("fb_post_ok", f"item={chosen_id} post={post_id}")
        log.info(f"[fb] DB frissítve — item #{chosen_id} → fb_posted_at=NOW")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
