"""
Zalaegerszeg 12 egyéni választókerülete — képviselők, utca→körzet mapping.
Forrás: mockup + helyi önkormányzati adatok.
"""

DISTRICTS = [
    {"number": 1, "name": "Belváros / Kaszaháza-dél",
     "representative_name": "Domján István",
     "representative_party": ""},
    {"number": 2, "name": "Ságod / Pózva",
     "representative_name": "Németh Gábor",
     "representative_party": ""},
    {"number": 3, "name": "Belváros-észak / Vizslapark",
     "representative_name": "Dr. Káldi Dávid",
     "representative_party": ""},
    {"number": 4, "name": "Kertváros / Alsóerdő",
     "representative_name": "Böjte Sándor Zsolt",
     "representative_party": ""},
    {"number": 5, "name": "Munkás / Berzsenyi",
     "representative_name": "Gecse Péter",
     "representative_party": ""},
    {"number": 6, "name": "Öreghegy / Botfa",
     "representative_name": "Bali Zoltán",
     "representative_party": ""},
    {"number": 7, "name": "Landorhegy / Neszele / Szenterzsébethegy",
     "representative_name": "Szilasi Gábor",
     "representative_party": "FIDESZ–KDNP"},
    {"number": 8, "name": "Bazita / Nekeresd",
     "representative_name": "Makovecz Tamás",
     "representative_party": ""},
    {"number": 9, "name": "Csács / Gógánhegy",
     "representative_name": "Galbavy Zoltán",
     "representative_party": ""},
    {"number": 10, "name": "Páterdombi / Jákum",
     "representative_name": "Bognár Ákos",
     "representative_party": ""},
    {"number": 11, "name": "Bekeháza / Zrínyi",
     "representative_name": "Orosz Ferencné",
     "representative_party": ""},
    {"number": 12, "name": "Ebergény / Szenterzsébethegy-dél",
     "representative_name": "Herkliné Ebedli Gy.",
     "representative_party": ""},
]

# Utcanév → körzet szám mapping (kisbetűs normalizált kulcsok)
# A regisztrációnál az utcanév alapján auto-assign
STREET_TO_DISTRICT = {
    # 01 — Belváros / Kaszaháza-dél
    "kossuth": 1, "deák": 1, "széchenyi": 1, "rákóczi": 1, "petőfi": 1,
    "ady endre": 1, "kazinczy": 1, "jókai": 1, "batthyány": 1,
    "dísz tér": 1, "szabadság tér": 1,

    # 02 — Ságod / Pózva
    "ságodi": 2, "pózva": 2,

    # 03 — Belváros-észak / Vizslapark
    "göcseji": 3, "kosztolányi": 3, "vizslapark": 3, "mártírok": 3,

    # 04 — Kertváros / Alsóerdő
    "kertváros": 4, "alsóerdő": 4, "platán": 4,

    # 05 — Munkás / Berzsenyi
    "berzsenyi": 5, "munkás": 5, "sport": 5,

    # 06 — Öreghegy / Botfa
    "öreghegy": 6, "botfa": 6,

    # 07 — Landorhegy / Neszele / Szenterzsébethegy
    "landorhegy": 7, "neszele": 7, "szenterzsébethegy": 7,
    "balatoni": 7, "olimpia": 7,

    # 08 — Bazita / Nekeresd
    "bazita": 8, "nekeresd": 8,

    # 09 — Csács / Gógánhegy
    "csács": 9, "gógánhegy": 9,

    # 10 — Páterdombi / Jákum
    "páterdomb": 10, "jákum": 10,

    # 11 — Bekeháza / Zrínyi
    "bekeháza": 11, "zrínyi": 11,

    # 12 — Ebergény / Szenterzsébethegy-dél
    "ebergény": 12,
}


def guess_district(street: str) -> int | None:
    """Try to guess district number from street name. Returns None if no match."""
    street_lower = street.lower().strip()
    for keyword, district_num in STREET_TO_DISTRICT.items():
        if keyword in street_lower:
            return district_num
    return None
