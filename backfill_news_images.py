#!/usr/bin/env python3
"""
Backfill: meglévő news_items rekordokhoz pótlólag letölti a képeket,
és a Google News URL-eket feloldja a tényleges forrás URL-re.

NEM nyúl az ai_summary-hez, sem a többi tartalmi mezőhöz — csak a
hiányzó kép + URL-feloldás. Idempotens: ahol már van image_local_path,
azt békén hagyja.

Használat:
    sudo -u zeghang /opt/zeghang/venv/bin/python /opt/zeghang/backfill_news_images.py

Opcionálisan limit:
    ... backfill_news_images.py 20    # csak 20 cikkre
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.database import get_db
from lib.news_fetcher import (
    resolve_real_url,
    fetch_article_content,
    fetch_event_detail,
    download_image,
    normalize_url,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def backfill(limit: int | None = None) -> None:
    conn = get_db()
    try:
        params = []
        limit_sql = ""
        if limit:
            limit_sql = "LIMIT %s"
            params.append(int(limit))
        rows = conn.execute(
            f"""SELECT id, category, source_url, title
                FROM news_items
                WHERE image_local_path IS NULL
                ORDER BY id ASC
                {limit_sql}""",
            tuple(params) if params else None,
        ).fetchall()

        log.info(f"Kép nélküli cikk: {len(rows)}")
        if not rows:
            return

        updated = 0
        for r in rows:
            row_id = r["id"]
            cat = r["category"]
            url = r["source_url"]
            title = r["title"]

            # 1. Hír: Google News URL feloldás + OG image
            if cat in ("local", "county"):
                # Ha még Google URL, dekódoljuk; ha már igazi forrás URL, akkor is
                # próbáljuk meg újra (egyszerű, nem érzékeny rá)
                real_url = resolve_real_url(url) if "news.google.com" in url else url
                if not real_url:
                    log.warning(f"#{row_id} skip — URL nem feloldható: {title[:60]}")
                    continue
                article = fetch_article_content(real_url)
                final_url = article.get("real_url") or real_url
                og_image = article.get("og_image")

            # 2. Esemény: direkt fetch_event_detail
            elif cat == "event":
                detail = fetch_event_detail(url)
                final_url = url
                og_image = detail.get("og_image")

            else:
                continue

            if not og_image:
                log.warning(f"#{row_id} nincs og:image: {title[:60]}")
                continue

            image_local = download_image(og_image)
            if not image_local:
                log.warning(f"#{row_id} kép-letöltés sikertelen: {title[:60]}")
                continue

            # UPDATE — csak a kép + URL + normalized_url, a többit hagyjuk
            try:
                conn.execute(
                    """UPDATE news_items
                       SET image_url = %s,
                           image_local_path = %s,
                           source_url = %s,
                           normalized_url = COALESCE(normalized_url, %s)
                       WHERE id = %s""",
                    (og_image, image_local, final_url, normalize_url(final_url), row_id),
                )
                conn.commit()
                updated += 1
                log.info(f"#{row_id} OK · {title[:60]}")
            except Exception as e:
                conn.rollback()
                log.warning(f"#{row_id} UPDATE failed: {e}")

        log.info(f"[done] {updated}/{len(rows)} cikk frissítve")
    finally:
        conn.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    backfill(limit)
