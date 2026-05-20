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
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

# Repo gyökeret a path-ba
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.database import get_db, init_db
from lib.ai import summarize_news, summarize_event
from lib.news_fetcher import (
    fetch_google_news,
    resolve_real_url,
    fetch_article_content,
    fetch_events,
    fetch_event_detail,
    download_image,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")[:120]
    except Exception:
        return ""


def _exists(conn, external_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM news_items WHERE external_id = %s",
        (external_id,),
    ).fetchone()
    return bool(row)


def process_news(category: str) -> int:
    """Helyi vagy megyei hírek beolvasása. Returns: új cikkek száma."""
    log.info(f"[{category}] Google News RSS lekérés…")
    items = fetch_google_news(category)
    log.info(f"[{category}] {len(items)} item az RSS-ben")

    inserted = 0
    conn = get_db()
    try:
        for item in items:
            if _exists(conn, item["external_id"]):
                continue

            # Resolve a real source URL
            real_url = resolve_real_url(item["source_url"]) or item["source_url"]
            article = fetch_article_content(real_url)

            # Source name: priorizáljuk az RSS-ből kapottat, ha nincs, domain
            source_name = item["source_name"] or _domain(article.get("real_url") or real_url)

            # AI summary
            content = article.get("content") or article.get("og_description") or ""
            ai_summary = summarize_news(item["title"], content) if content else None

            # Image
            image_local = download_image(article.get("og_image")) if article.get("og_image") else None

            try:
                conn.execute(
                    """
                    INSERT INTO news_items
                      (category, external_id, source_url, source_name, title,
                       ai_summary, image_url, image_local_path, published_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (
                        category,
                        item["external_id"],
                        article.get("real_url") or real_url,
                        source_name,
                        item["title"],
                        ai_summary,
                        article.get("og_image"),
                        image_local,
                        item["published_at"],
                    ),
                )
                conn.commit()
                inserted += 1
                log.info(f"[{category}] + {item['title'][:80]}")
            except Exception as e:
                conn.rollback()
                log.warning(f"[{category}] INSERT failed: {e}")
    finally:
        conn.close()

    log.info(f"[{category}] {inserted} új cikk hozzáadva")
    return inserted


def process_events() -> int:
    """Zalaegerszegturizmus.hu programok. Returns: új események száma."""
    log.info("[events] zalaegerszegturizmus.hu/programok scrape…")
    items = fetch_events()
    log.info(f"[events] {len(items)} esemény a listán")

    inserted = 0
    conn = get_db()
    try:
        for item in items:
            if _exists(conn, item["external_id"]):
                continue

            detail = fetch_event_detail(item["source_url"])
            content = detail.get("content") or ""
            ai_summary = summarize_event(item["title"], content) if content else None
            image_local = download_image(detail.get("og_image")) if detail.get("og_image") else None

            try:
                conn.execute(
                    """
                    INSERT INTO news_items
                      (category, external_id, source_url, source_name, title,
                       ai_summary, image_url, image_local_path,
                       event_start_at, event_end_at, event_location)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (
                        "event",
                        item["external_id"],
                        item["source_url"],
                        item["source_name"],
                        item["title"],
                        ai_summary,
                        detail.get("og_image"),
                        image_local,
                        detail.get("event_start_at"),
                        detail.get("event_end_at"),
                        detail.get("event_location"),
                    ),
                )
                conn.commit()
                inserted += 1
                log.info(f"[events] + {item['title'][:80]}")
            except Exception as e:
                conn.rollback()
                log.warning(f"[events] INSERT failed: {e}")
    finally:
        conn.close()

    log.info(f"[events] {inserted} új esemény hozzáadva")
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
    try:
        init_db()
    except Exception as e:
        log.warning(f"init_db: {e}")

    total = 0
    total += process_news("local")
    total += process_news("county")
    total += process_events()
    purge_old(90)
    log.info(f"[done] {total} új item")


if __name__ == "__main__":
    main()
