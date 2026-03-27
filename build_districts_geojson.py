#!/usr/bin/env python3 -u
"""
Build district GeoJSON from Overpass OSM data + official street-to-district mapping.

1. Reads overpass_streets.json (all ZEG streets from OpenStreetMap)
2. Reads zeg_streets.json (official street->szavazokor mapping from zalaegerszeg.hu)
3. Matches streets, groups by EVK, computes convex hull polygons
4. Outputs static/districts.geojson

Usage: python build_districts_geojson.py
"""

import json
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent

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


def strip_accents(s):
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


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


def expand_hull(hull, factor=0.001):
    """Expand hull outward from centroid."""
    if len(hull) < 3:
        return hull
    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)
    expanded = []
    for x, y in hull:
        dx, dy = x - cx, y - cy
        length = (dx**2 + dy**2) ** 0.5
        if length > 0:
            expanded.append((x + dx / length * factor, y + dy / length * factor))
        else:
            expanded.append((x, y))
    return expanded


def main():
    # 1. Load Overpass street data
    with open(BASE / "overpass_streets.json", encoding="utf-8") as f:
        osm = json.load(f)

    # Build lookup: normalized street name -> list of (lat, lon)
    osm_streets = defaultdict(list)
    for el in osm["elements"]:
        name = el.get("tags", {}).get("name")
        center = el.get("center")
        if name and center:
            key = strip_accents(name)
            osm_streets[key].append((center["lat"], center["lon"]))

    print(f"OSM: {len(osm_streets)} unique street names, {sum(len(v) for v in osm_streets.values())} segments")

    # 2. Load official street->szavazokor mapping
    with open(BASE / "zeg_streets.json", encoding="utf-8") as f:
        zeg_streets = json.load(f)

    print(f"Official: {len(zeg_streets)} street records")

    # 3. Match streets and assign to EVK
    evk_points = defaultdict(list)
    matched = 0
    unmatched = []

    # Get unique street names per szavazokor
    szk_streets = defaultdict(set)
    for rec in zeg_streets:
        szk = rec["korzet"]
        name = rec["nev"]
        tipus = rec.get("tipus", "utca")
        szk_streets[szk].add((name, tipus))

    for szk, streets in sorted(szk_streets.items()):
        evk = SZK_TO_EVK.get(szk)
        if not evk:
            continue

        for name, tipus in streets:
            # Try exact match with type
            full = strip_accents(f"{name} {tipus}")
            coords = osm_streets.get(full)

            if not coords:
                # Try without type
                key = strip_accents(name)
                for osm_key in osm_streets:
                    if osm_key.startswith(key + " ") or osm_key == key:
                        coords = osm_streets[osm_key]
                        break

            if not coords:
                # Try partial match
                key = strip_accents(name)
                for osm_key in osm_streets:
                    if key in osm_key or osm_key in key:
                        coords = osm_streets[osm_key]
                        break

            if coords:
                matched += 1
                for lat, lon in coords:
                    evk_points[evk].append((lon, lat))  # GeoJSON = [lng, lat]
            else:
                unmatched.append(f"EVK {evk}: {name} {tipus}")

    print(f"\nMatched: {matched} streets")
    print(f"Unmatched: {len(unmatched)} streets")
    if unmatched[:10]:
        for u in unmatched[:10]:
            print(f"  {u}")
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched) - 10} more")

    # 4. Generate GeoJSON - polygons + centroids
    features = []
    for evk in range(1, 13):
        points = evk_points.get(evk, [])
        print(f"\nEVK {evk}: {len(points)} points")

        if not points:
            print(f"  WARNING: no points, skipping")
            continue

        pop = sum(SZK_POP.get(szk, 0) for szk in EVK_SZK[evk])

        # Polygon (convex hull)
        if len(points) >= 3:
            hull = convex_hull(points)
            hull = expand_hull(hull)
            coords = hull + [hull[0]]  # close polygon
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

        # Centroid (point)
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

    output = BASE / "static" / "districts.geojson"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {output} with {len(features)} features (polygons + centroids)")


if __name__ == "__main__":
    main()
