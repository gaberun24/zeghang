"""
Zalaegerszeg 12 egyéni választókerülete — képviselők, szavazókör→körzet mapping,
és teljes utca→szavazókör adatbázis a zalaegerszeg.hu hivatalos adatai alapján.

Forrás: https://zalaegerszeg.hu/ki-az-en-kepviselom/
"""

import json
import os
import re
import unicodedata

# ── Ékezet eltávolítás (accent-insensitive kereséshez) ─────────────

def _strip_accents(s: str) -> str:
    """Remove Hungarian accents: á→a, é→e, í→i, ó→o, ö→o, ő→o, ú→u, ü→u, ű→u"""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

# ── Képviselők ──────────────────────────────────────────────────────

DISTRICTS = [
    {"number": 1, "representative_name": "Domján István",
     "representative_party": "FIDESZ–KDNP", "voters": 3785},
    {"number": 2, "representative_name": "Németh Gábor",
     "representative_party": "FIDESZ–KDNP", "voters": 3599},
    {"number": 3, "representative_name": "Dr. Káldi Dávid",
     "representative_party": "FIDESZ–KDNP", "voters": 3532},
    {"number": 4, "representative_name": "Böjte Sándor Zsolt",
     "representative_party": "FIDESZ–KDNP", "voters": 3293},
    {"number": 5, "representative_name": "Gecse Péter",
     "representative_party": "FIDESZ–KDNP", "voters": 4318},
    {"number": 6, "representative_name": "Bali Zoltán",
     "representative_party": "FIDESZ–KDNP", "voters": 3775},
    {"number": 7, "representative_name": "Szilasi Gábor",
     "representative_party": "FIDESZ–KDNP", "voters": 4211},
    {"number": 8, "representative_name": "Makovecz Tamás",
     "representative_party": "FIDESZ–KDNP", "voters": 3944},
    {"number": 9, "representative_name": "Galbavy Zoltán",
     "representative_party": "FIDESZ–KDNP", "voters": 3009},
    {"number": 10, "representative_name": "Bognár Ákos",
     "representative_party": "FIDESZ–KDNP", "voters": 4132},
    {"number": 11, "representative_name": "Orosz Ferencné",
     "representative_party": "FIDESZ–KDNP", "voters": 4046},
    {"number": 12, "representative_name": "Herkliné Ebedli Gyöngyi",
     "representative_party": "FIDESZ–KDNP", "voters": 3603},
]

# ── Szavazókör → Körzet mapping ────────────────────────────────────
# Kulcs: szavazókör kód (str, 3 jegyű), Érték: körzet szám (int, 1-12)

SZAVAZOKOR_TO_KORZET = {}
_korzet_data = {
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
for _korzet_num, _szavazokor_list in _korzet_data.items():
    for _szk in _szavazokor_list:
        SZAVAZOKOR_TO_KORZET[_szk] = _korzet_num

# ── Utca adatbázis betöltése ───────────────────────────────────────

_streets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "streets_compact.json")
with open(_streets_path, "r", encoding="utf-8") as _f:
    STREETS = json.load(_f)

# Index: utcanév (kisbetűs, ékezet nélkül) → lista az összes bejegyzésből
_STREET_INDEX = {}
for _entry in STREETS:
    _key = _strip_accents(_entry["nev"].lower())
    _STREET_INDEX.setdefault(_key, []).append(_entry)


def _normalize_street_name(raw: str) -> tuple[str, str | None, int | None]:
    """
    Parse a raw address string into (street_name, street_type, house_number).
    Examples:
        "Landorhegyi út 15"  → ("landorhegyi", "út", 15)
        "Kossuth Lajos utca" → ("kossuth lajos", "utca", None)
        "Petőfi u. 3/A"     → ("petőfi", "utca", 3)
        "Ady Endre utca 34" → ("ady endre", "utca", 34)
    """
    raw = raw.strip()
    if not raw:
        return ("", None, None)

    # Known street types — both accented and unaccented forms
    type_map = {
        "útja": "útja", "utja": "útja",
        "liget": "liget", "kert": "kert",
        "tető": "tető", "teto": "tető",
        "udvar": "udvar",
        "köz": "köz", "koz": "köz",
        "sor": "sor",
        "tér": "tér", "ter": "tér",
        "utca": "utca",
        "út": "út", "ut": "út",
        "u.": "utca",
    }

    raw_lower = raw.lower()

    # Extract house number from end (e.g. "15", "3/A", "12-14", "7.sz")
    house_num = None
    house_match = re.search(r'(\d+)\s*[/\-\.]?\s*[a-zA-Z]?\s*\.?\s*$', raw)
    if house_match:
        house_num = int(house_match.group(1))
        # Remove house number part from the string
        raw_lower = raw_lower[:house_match.start()].strip()

    # Detect and remove street type (match as whole word or at end)
    street_type = None
    for abbr, full_type in type_map.items():
        pattern = r'\b' + re.escape(abbr) + r'(?:\b|$|\.)'
        m = re.search(pattern, raw_lower)
        if m and m.start() > 0:
            street_type = full_type
            raw_lower = raw_lower[:m.start()].strip()
            break

    street_name = _strip_accents(raw_lower.strip().rstrip("."))
    return (street_name, street_type, house_num)


def _matches_parity(house_num: int, haz_type: str) -> bool:
    """Check if a house number matches the parity rule."""
    if haz_type == "Teljes közterület" or haz_type == "Folyamatos házszámok":
        return True
    if haz_type == "Páratlan házszámok":
        return house_num % 2 == 1
    if haz_type == "Páros házszámok":
        return house_num % 2 == 0
    return True


def guess_district(address: str) -> int | None:
    """
    Determine district number from a Zalaegerszeg address.
    Uses the official zalaegerszeg.hu street→szavazókör→körzet database.

    Returns district number (1-12) or None if no match.
    """
    street_name, street_type, house_num = _normalize_street_name(address)
    if not street_name:
        return None

    entries = _STREET_INDEX.get(street_name)
    if not entries:
        # Fuzzy: try matching as substring
        for key in _STREET_INDEX:
            if street_name in key or key in street_name:
                entries = _STREET_INDEX[key]
                break
    if not entries:
        return None

    # Filter by street type if provided
    if street_type and len(entries) > 1:
        typed = [e for e in entries if e["tipus"] == street_type]
        if typed:
            entries = typed

    # If we have a house number, find the matching range
    if house_num is not None:
        for entry in entries:
            tol = entry["tol"]
            ig = entry["ig"]
            # tol=0, ig=999999 means entire street — always matches
            if tol == 0 and ig == 999999:
                if _matches_parity(house_num, entry["haz"]):
                    szk = entry["korzet"]
                    return SZAVAZOKOR_TO_KORZET.get(szk)
            elif tol <= house_num <= ig and _matches_parity(house_num, entry["haz"]):
                szk = entry["korzet"]
                return SZAVAZOKOR_TO_KORZET.get(szk)
        # No range matched — try "Teljes közterület" entries as fallback
        for entry in entries:
            if entry["haz"] == "Teljes közterület":
                szk = entry["korzet"]
                return SZAVAZOKOR_TO_KORZET.get(szk)

    # No house number — return first "Teljes közterület" or first entry
    for entry in entries:
        if entry["haz"] == "Teljes közterület":
            szk = entry["korzet"]
            return SZAVAZOKOR_TO_KORZET.get(szk)

    # Fallback: first entry
    szk = entries[0]["korzet"]
    return SZAVAZOKOR_TO_KORZET.get(szk)
