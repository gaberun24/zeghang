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
    normalize_url,
    title_hash,
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

            # Resolve a real source URL (HTTP redirect)
            real_url = resolve_real_url(item["source_url"]) or item["source_url"]
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
                       title_hash, normalized_url,
                       ai_summary, image_url, image_local_path, published_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (
                        category,
                        item["external_id"],
                        final_url,
                        source_name,
                        item["title"],
                        t_hash,
                        norm_url,
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

    log.info(
        f"[{category}] {inserted} új · skip: guid={skipped['guid']} "
        f"url={skipped['url']} title={skipped['title']}"
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
            content = detail.get("content") or ""
            ai_summary = summarize_event(item["title"], content) if content else None
            image_local = download_image(detail.get("og_image")) if detail.get("og_image") else None

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
                        item["title"],
                        t_hash,
                        norm_url,
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
