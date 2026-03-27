# Zalaegerszeg Hangja (Z!)

Független, nonprofit közösségi platform Zalaegerszeg lakosai számára. Közterületi problémák bejelentése, szavazás, priorizálás és átláthatóvá tétel — közvetlen kapcsolat a lakók között.

**Élő oldal:** [zeghang.hajasgabor.com](https://zeghang.hajasgabor.com)

---

## Funkciók

### Alapfunkciók
- **Probléma bejelentés** — cím, leírás, kategória, fotó, utca-autocomplete, térképi helymegjelölés
- **Szavazás** — anonim 👍/👎 szavazás, körzeti arányosítással súlyozva
- **12 választókerület** — minden körzet saját toplistával és képviselővel
- **Áttekintő** — körzeti statisztikák, aktív/megoldott problémák, részvételi arány
- **Térkép** — Leaflet + GeoJSON körzeti megjelenítés, issue markerek
- **Közösségi megoldás-szavazás** — bárki jelezheti hogy egy probléma megoldódott, 7 napos szavazás dönt

### AI funkciók (GPT-4o-mini)
- **Kategória javaslat** — 6 kategória egyikét javasolja a szöveg alapján
- **Sürgősség-értékelés** — 4 fokozatú (alacsony/közepes/magas/sürgős)
- **Duplikátum-felismerés** — összeveti az utolsó 50 nyitott bejelentéssel, megmutatja a hasonlót
- **Tartalomszűrés** — nem közterületi panaszok (magánügy, üzleti, spam, politika) kiszűrése
- **Valós idejű autocomplete** — gépelés közben kategória javaslat

### Moderáció és biztonság
- **Trágárságszűrő** — magyar csúnyaszó-lista automatikus csillagozással (Jinja2 `|censor` filter)
- **Troll védelem** — reputáció-alapú shadowban, rate limit
- **Admin felület** — bejelentések/felhasználók/hozzászólások kezelése, ban, elrejtés
- **Cookie consent** + **segélyhívó figyelmeztetés** (112)

### Felhasználói funkciók
- **Reputációs rendszer** — pontgyűjtés hasznos bejelentésekért, szintek és jelvények
- **Push értesítések** — PWA web push, felhasználói beállításokban ki/bekapcsolható
- **Elfelejtett jelszó** — Brevo email API-val jelszó-visszaállítás
- **Címmódosítás** — évente 1x megengedett
- **Beállítások oldal** — értesítések, megjelenítési név, lakcím kezelése

### Mobil és PWA
- **Teljes mobil responsive** — 1024px / 768px / 400px breakpointok, hamburger menü
- **PWA manifest** — telepíthető app Android (Chrome) és iPhone (Safari) eszközökre
- **Használati útmutató** — telepítési leírással Android/iPhone-ra

## Tech stack

| Réteg | Technológia |
|-------|-------------|
| Backend | Python 3 / Flask |
| Adatbázis | PostgreSQL (psycopg2, connection pool) |
| AI | OpenAI GPT-4o-mini API |
| Email | Brevo (Sendinblue) API |
| Frontend | HTML/CSS/JS, Leaflet térkép |
| Szerver | Gunicorn + Nginx reverse proxy |
| Auth | Flask-Login, Flask-WTF (CSRF), bcrypt |
| Push | Web Push API (VAPID), Service Worker |

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
   - `BREVO_API_KEY` — Brevo email API kulcs
   - `BREVO_SENDER_EMAIL` — feladó email cím
   - `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` — push értesítésekhez
   - `UPLOAD_DIR` — fotó feltöltési mappa
   - `MAX_UPLOAD_MB` — max feltöltési méret

4. VAPID kulcsok generálása (push értesítésekhez):
   ```bash
   bash setup-vapid.sh
   ```

5. Indítsd el:
   ```bash
   flask run
   ```

## Projektstruktúra

```
├── app.py                  # Flask alkalmazás, összes route
├── lib/
│   ├── ai.py               # OpenAI integráció (kategorizálás, duplikáció, sürgősség)
│   ├── config.py            # Környezeti változók
│   ├── database.py          # PostgreSQL connection pool, migrációk
│   ├── email.py             # Brevo email küldés (jelszó-visszaállítás)
│   ├── moderation.py        # Trágárságszűrő
│   └── notifications.py     # Web push értesítések
├── templates/
│   ├── admin/               # Admin felület sablonok
│   ├── base.html            # Publikus oldal alap
│   ├── app_base.html        # Bejelentkezett felület alap
│   ├── dashboard.html       # Áttekintő (fő felület)
│   ├── guide.html           # Használati útmutató
│   ├── settings.html        # Felhasználói beállítások
│   └── ...                  # További sablonok
├── static/
│   ├── css/style.css        # Stíluslap (responsive)
│   ├── js/app.js            # Frontend JS
│   ├── sw.js                # Service Worker (push)
│   ├── manifest.json        # PWA manifest
│   ├── icon-192.png         # PWA ikon
│   ├── icon-512.png         # PWA ikon
│   └── districts.geojson    # Körzeti térképadatok
├── install.sh               # Automatikus telepítő script
├── setup-vapid.sh           # VAPID kulcs generáló
├── requirements.txt         # Python függőségek
└── .env.example             # Konfiguráció minta
```

## Licensz

Open source. A forráskód nyilvánosan elérhető és auditálható.

---

*Készítette: Hajas Gábor · Zalaegerszeg · 2026*
