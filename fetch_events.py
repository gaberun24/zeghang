#!/usr/bin/env python3
"""
Program-aggregátor CLI script — csak a zalaegerszegturizmus.hu/programok
oldalt scrape-eli, AI ajánló generálással. A hírektől különválasztva, mert:
- Programok ritkábban frissülnek → napi 1x elég
- A user-nek debug szempontból tisztább külön

Cron (napi 04:00):
    0 4 * * * /opt/zeghang/venv/bin/python /opt/zeghang/fetch_events.py >> /opt/zeghang/events.log 2>&1

Idempotens: dedup external_id + normalized_url + title_hash alapján,
így naponta futva csak az új programokat veszi fel.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A fetch_news.py-ban van a teljes process_events() logika — onnan importáljuk,
# hogy ne duplikáljuk a kódot.
from fetch_news import process_events, log as fetch_log
from lib.database import init_db


def main():
    try:
        init_db()
    except Exception as e:
        fetch_log.warning(f"init_db: {e}")

    fetch_log.info("=== fetch_events.py indul ===")
    new_count = process_events()
    fetch_log.info(f"=== fetch_events.py done · {new_count} új program ===")


if __name__ == "__main__":
    main()
