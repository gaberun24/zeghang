# Zalaegerszeg Hangja (Z!)

Független közösségi platform Zalaegerszeg lakosai számára. A cél: közterületi problémák bejelentése, szavazás, priorizálás és átláthatóvá tétel — közvetlen kapcsolat a lakók és a választott képviselők között.

**Élő oldal:** [zeghang.hajasgabor.com](https://zeghang.hajasgabor.com)

---

## Funkciók

- **Probléma bejelentés** — cím, leírás, kategória, fotó, térképi helymegjelölés
- **Szavazás** — anonim fel/leszavazás, körzeti arányosítással súlyozva
- **AI feldolgozás** — GPT-4o-mini automatikus kategorizálás, sürgősség-értékelés, duplikátum-felismerés
- **12 választókerület** — minden körzet saját toplistával és képviselővel
- **Dashboard** — körzeti statisztikák, aktív/megoldott problémák, részvételi arány
- **Térkép** — Leaflet + GeoJSON körzeti megjelenítés, issue markerek
- **Adatvédelem** — bcrypt jelszó, SHA-256 lakcím hash, anonim szavazat, GDPR-konform

## Tech stack

| Réteg | Technológia |
|-------|-------------|
| Backend | Python 3 / Flask |
| Adatbázis | PostgreSQL (psycopg2, connection pool) |
| AI | OpenAI GPT-4o-mini API |
| Frontend | HTML/CSS/JS, Leaflet térkép |
| Szerver | Gunicorn + Nginx reverse proxy |
| Auth | Flask-Login, Flask-WTF (CSRF), bcrypt |

## Telepítés

### Automatikus (Debian/Ubuntu)

```bash
bash install.sh
```

Ez beállítja a teljes stacket: PostgreSQL, Python venv, systemd service, Nginx, UFW tűzfal.

### Manuális

1. Klónozd a repót:
   ```bash
   git clone https://github.com/gaberun24/zeghang.git
   cd zeghang
   ```

2. Hozz létre Python venv-et és telepítsd a függőségeket:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Másold és töltsd ki a `.env` fájlt:
   ```bash
   cp .env.example .env
   nano .env
   ```

   Szükséges változók:
   - `FLASK_SECRET_KEY` — session titkosítás
   - `DATABASE_URL` — PostgreSQL connection string
   - `OPENAI_API_KEY` — GPT-4o-mini API kulcs
   - `OPENAI_MODEL` — modell neve (alapértelmezett: `gpt-4o-mini`)
   - `UPLOAD_DIR` — fotó feltöltési mappa
   - `MAX_UPLOAD_MB` — max feltöltési méret

4. Indítsd el:
   ```bash
   flask run
   ```

## Projektstruktúra

```
├── app.py                  # Flask alkalmazás, összes route
├── lib/
│   ├── ai.py               # OpenAI integráció (kategorizálás, duplikáció, sürgősség)
│   ├── config.py            # Környezeti változók
│   └── database.py          # PostgreSQL connection pool, modellek
├── templates/               # Jinja2 HTML sablonok
├── static/
│   ├── css/style.css        # Stíluslap
│   ├── js/app.js            # Frontend JS
│   └── districts.geojson    # Körzeti térképadatok
├── install.sh               # Automatikus telepítő script
├── requirements.txt         # Python függőségek
└── .env.example             # Konfiguráció minta
```

## AI működés

A platform három ponton használ mesterséges intelligenciát:

1. **Kategória javaslat** (`categorize_issue`) — a bejelentés szövege alapján 6 kategória egyikét javasolja (közút, park, biztonság, infrastruktúra, közlekedés, egyéb) + sürgősségi szintet ad
2. **Duplikátum-felismerés** (`check_duplicates`) — összeveti az új bejelentést a körzet utolsó 50 nyitott ügyével
3. **Valós idejű autocomplete** (`quick_categorize`) — AJAX endpointon keresztül, gépelés közben javasol kategóriát

Az AI soha nem dönt — kizárólag javasol. A felhasználó bármikor felülírhatja. Ha az API nem elérhető, a platform tovább működik alapértelmezett értékekkel.

## Licensz

Open source. A forráskód nyilvánosan elérhető és auditálható.

---

*Készítette: Hajas Gábor · Zalaegerszeg · 2026*
