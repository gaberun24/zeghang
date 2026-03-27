#!/usr/bin/env python3
"""
Geocode district boundaries using house-number-level Nominatim queries.

For each street entry in zeg_streets.json:
- "Teljes közterület": geocode the street name once
- House number ranges: geocode start, middle, end of range

Uses Nominatim with 1 req/sec rate limit. Results cached in geocode_cache.json
so re-runs skip already-resolved addresses.

Usage: python geocode_houses.py
"""

import json
import time
import urllib.request
import urllib.parse
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent
CACHE_FILE = BASE / "geocode_cache.json"
STREETS_FILE = BASE / "zeg_streets.json"
OUTPUT_FILE = BASE / "static" / "districts.geojson"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ZEGHang-DistrictMapper/1.0"

# --- EVK mapping ---
EVK_SZK = {
    1: ["001", "002", "003", "009"],
    2: ["004", "005", "006"],
    3: ["016", "018", "019", "020"],
    4: ["010", "011", "012", "015"],
    5: ["042", "047", "048", "049", "050"],
    6: ["007", "021", "022", "023"],
    7: ["024", "025", "026", "027", "032"],
    8: ["008", "028", "029", "030", "031"],
    9: ["037", "040", "041"],
    10: ["033", "034", "035", "036", "039"],
    11: ["038", "043", "044", "045", "046"],
    12: ["013", "014", "017", "051"],
}
SZK_TO_EVK = {}
for evk, szks in EVK_SZK.items():
    for szk in szks:
        SZK_TO_EVK[szk] = evk

SZK_POP = {
    "001": 760, "002": 901, "003": 1148, "004": 1297, "005": 947,
    "006": 1355, "007": 733, "008": 658, "009": 976, "010": 809,
    "011": 667, "012": 950, "013": 1179, "014": 928, "015": 867,
    "016": 870, "017": 872, "018": 868, "019": 864, "020": 930,
    "021": 1103, "022": 839, "023": 1100, "024": 510, "025": 626,
    "026": 1238, "027": 1132, "028": 1363, "029": 796, "030": 523,
    "031": 604, "032": 705, "033": 721, "034": 911, "035": 823,
    "036": 921, "037": 979, "038": 762, "039": 756, "040": 1028,
    "041": 1002, "042": 656, "043": 877, "044": 885, "045": 759,
    "046": 763, "047": 652, "048": 1331, "049": 982, "050": 697,
    "051": 624,
}

REPRESENTATIVES = {
    1: "Domján István", 2: "Németh Gábor", 3: "Dr. Káldi Dávid",
    4: "Böjte Sándor Zsolt", 5: "Gecse Péter", 6: "Bali Zoltán",
    7: "Szilasi Gábor", 8: "Makovecz Tamás", 9: "Galbavy Zoltán",
    10: "Bognár Ákos", 11: "Orosz Ferencné", 12: "Herkliné Ebedli Gyöngyi",
}


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def geocode(query, cache, max_retries=3):
    """Geocode a single address string. Returns (lat, lon) or None.
    Retries on network/server errors. Only caches None for genuine 'not found'."""
    if query in cache:
        val = cache[query]
        if val is None:
            return None
        return tuple(val)

    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "hu",
        "viewbox": "16.7,46.9,16.95,46.78",
        "bounded": 1,
    })
    url = f"{NOMINATIM_URL}?{params}"

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break  # success
        except Exception as e:
            is_429 = "429" in str(e)
            wait = attempt * 60 if is_429 else attempt * 10
            print(f"    RETRY {attempt}/{max_retries}: {e} — waiting {wait}s...")
            time.sleep(wait)
            if attempt == max_retries:
                print(f"    FAILED after {max_retries} retries: {query}")
                # Don't cache — will retry next run
                return None
            continue

    time.sleep(3)  # Nominatim rate limit — 1 req per 3 sec to stay safe

    if data:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        cache[query] = [lat, lon]
        return (lat, lon)
    else:
        cache[query] = None  # genuinely not found
        return None


def sample_house_numbers(tol, ig, haz_type):
    """Generate sample house numbers for a range."""
    # Cap crazy ranges
    ig = min(ig, 300)

    if haz_type == "Páratlan házszámok":
        nums = list(range(tol if tol % 2 == 1 else tol + 1, ig + 1, 2))
    elif haz_type == "Páros házszámok":
        start = tol if tol % 2 == 0 else tol + 1
        if start == 0:
            start = 2
        nums = list(range(start, ig + 1, 2))
    else:  # Folyamatos házszámok
        nums = list(range(tol, ig + 1))

    if not nums:
        return [tol]

    # Sample: start, end, and up to 3 evenly spaced points in between
    if len(nums) <= 5:
        return nums

    samples = [nums[0]]
    step = len(nums) // 4
    for i in range(1, 4):
        samples.append(nums[i * step])
    samples.append(nums[-1])
    return samples


def convex_hull(points):
    """Graham scan convex hull."""
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def expand_hull(hull, factor=0.0005):
    """Slightly expand hull outward from centroid."""
    if len(hull) < 3:
        return hull
    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)
    return [
        (cx + (x - cx) * (1 + factor), cy + (y - cy) * (1 + factor))
        for x, y in hull
    ]


def main():
    with open(STREETS_FILE, "r", encoding="utf-8") as f:
        streets = json.load(f)

    cache = load_cache()
    cached_before = len(cache)
    print(f"Loaded {cached_before} cached geocode results")

    evk_points = defaultdict(list)
    total_queries = 0
    hits = 0
    misses = 0

    for i, entry in enumerate(streets):
        nev = entry["nev"]
        tipus = entry["tipus"]
        tol = entry["tol"]
        ig = entry["ig"]
        haz = entry["haz"]
        korzet = entry["korzet"]
        evk = SZK_TO_EVK.get(korzet)

        if not evk:
            continue

        street_full = f"{nev} {tipus}"

        if haz == "Teljes közterület" or tol == 0:
            # Just geocode the street
            query = f"{street_full}, Zalaegerszeg"
            total_queries += 1
            result = geocode(query, cache)
            if result:
                hits += 1
                lat, lon = result
                evk_points[evk].append((lon, lat))
            else:
                misses += 1
        else:
            # House number range — sample a few points
            samples = sample_house_numbers(tol, ig, haz)
            for num in samples:
                query = f"{street_full} {num}, Zalaegerszeg"
                total_queries += 1
                result = geocode(query, cache)
                if result:
                    hits += 1
                    lat, lon = result
                    evk_points[evk].append((lon, lat))
                else:
                    misses += 1

        # Progress
        if (i + 1) % 20 == 0 or i == len(streets) - 1:
            new_queries = len(cache) - cached_before
            print(f"[{i+1}/{len(streets)}] queries: {total_queries}, "
                  f"hits: {hits}, misses: {misses}, "
                  f"new API calls: {new_queries}")
            save_cache(cache)

    save_cache(cache)
    print(f"\nDone! {total_queries} queries, {hits} hits, {misses} misses")
    print(f"Cache now has {len(cache)} entries ({len(cache) - cached_before} new)")

    # Generate GeoJSON
    features = []
    for evk in range(1, 13):
        points = evk_points.get(evk, [])
        print(f"\nEVK {evk}: {len(points)} coordinate points")

        if not points:
            print(f"  WARNING: no points, skipping")
            continue

        pop = sum(SZK_POP.get(szk, 0) for szk in EVK_SZK[evk])

        # Polygon (convex hull)
        if len(points) >= 3:
            hull = convex_hull(points)
            hull = expand_hull(hull)
            coords = hull + [hull[0]]
            features.append({
                "type": "Feature",
                "properties": {
                    "district": evk,
                    "representative": REPRESENTATIVES[evk],
                    "population": pop,
                    "layer": "polygon",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                }
            })

        # Centroid marker
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        features.append({
            "type": "Feature",
            "properties": {
                "district": evk,
                "representative": REPRESENTATIVES[evk],
                "population": pop,
                "layer": "centroid",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [cx, cy],
            }
        })

    geojson = {"type": "FeatureCollection", "features": features}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {OUTPUT_FILE} with {len(features)} features")


if __name__ == "__main__":
    main()
