# Zalaegerszeg Hangja (Z!)

Független, nonprofit közösségi platform Zalaegerszeg lakosai számára. Közterületi problémák bejelentése, szavazás, priorizálás és átláthatóvá tétel — közvetlen kapcsolat a lakók között.

**Élő oldal:** [zeghangja.hu](https://zeghangja.hu)

---

## Funkciók

### Alapfunkciók
- **Probléma bejelentés** — cím, leírás, kategória, fotó, utca-autocomplete, térképi helymegjelölés, opcionális GPS koordináta
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
- **Prompt injection védelem** — system message + JSON-encoded user input, az LLM nem követi a tartalmon belüli utasításokat

### Moderáció és biztonság
- **Trágárságszűrő** — magyar csúnyaszó-lista automatikus csillagozással (Jinja2 `|censor` filter)
- **Troll védelem** — reputáció-alapú shadowban, IP rate limit (login 5/5 perc, password reset 3/10 perc, regisztráció 3/óra)
- **CSRF védelem** — flask-wtf globális, JSON POST-on X-CSRFToken header
- **Pillow zip-bomb védelem** — `MAX_IMAGE_PIXELS=50M` + explicit `DecompressionBombError` kezelés
- **Path traversal safety** — `realpath` prefix check képfeltöltéskor
- **Admin felület** — bejelentések/felhasználók/hozzászólások kezelése (pagination), ban, elrejtés
- **Admin statisztikák** — látogatottság, kategóriák, körzeti aktivitás, top felhasználók
- **Rendszer állapot** — CPU, memória, HDD, uptime monitorozás az admin felületen
- **Biztonsági napló** — sikertelen bejelentkezések, tiltott hozzáférések, admin műveletek logolása; email-ek SHA-256 hash-ként (GDPR data minimization)
- **Email riasztások** — Brevo értesítés adminnak gyanús tevékenységről
- **Cookie consent** — granuláris (csak szükséges / minden elfogadása), verziózott, visszavonható a footerben

### Felhasználói funkciók
- **18+ életkor ellenőrzés** — regisztrációnál születési dátum alapján, a dátum **nem kerül tárolásra**
- **Jelszó megjelenítés** — toggle gomb (szem ikon) a login, register és jelszó-visszaállító oldalakon
- **Reputációs rendszer** — pontgyűjtés hasznos bejelentésekért, szintek és jelvények
- **Push értesítések** — PWA web push, felhasználói beállításokban ki/bekapcsolható
- **Elfelejtett jelszó** — Brevo email API-val jelszó-visszaállítás (1 órás token, one-time use)
- **Címmódosítás** — évente 1x megengedett
- **Beállítások oldal** — értesítések, megjelenítési név, lakcím kezelése

### GDPR / adatvédelem
- **16 szekciós GDPR-megfelelő adatvédelmi tájékoztató** — jogalap-tábla (Art. 6), címzettek, EU-n kívüli adattovábbítás (SCC/DPF), automatizált döntéshozatal (Art. 22), NAIH elérhetőség, 72 órás incidens-bejelentés (Art. 33-34)
- **Lakcím SHA-256 hash** — a pontos cím soha nem kerül DB-be, csak a hash és a körzet-azonosító
- **Jelszó bcrypt** — egyedi salttal, default 12 rounds
- **Érintetti jogok** — hozzáférés, helyesbítés, törlés, korlátozás, adathordozhatóság, tiltakozás, automatizált döntéssel szembeni jog
- **Cookie consent visszavonhatóság** — footer link vagy `/adatvedelem` oldal

### SEO
- **Meta tagek** — description, canonical, Open Graph, Twitter Card minden publikus oldalon (oldalspecifikus `meta_description` block)
- **Social preview kép** — 1200×630 `og-image.png`
- **Schema.org JSON-LD** — Organization + WebSite (Google Knowledge Graph-hoz)
- **`/robots.txt`** — admin/api/uploads disallow, sitemap hivatkozás
- **`/sitemap.xml`** — 5 publikus oldal, prioritással
- **Cache-busting** — `url_for('static', ...)` automatikusan megkapja a `?v=<commit-hash>` query stringet, minden deploy után friss CSS/JS
- **Kanonikus `SITE_URL`** — `.env`-ből, nem a request-ből (Cloudflare Flexible SSL mögött is biztos HTTPS)

### Megjelenés
- **Sötét/világos téma** — rendszer-függő vagy kézi váltás a beállításokban
- **Nap/Hold animáció** — valós idejű égitest-mozgás a dombok felett, napszakfüggő színvilág
- **Csillagos égbolt** — éjszaka animált csillagok a hero szekcióban
- **Teljes mobil responsive** — 1024px / 768px / 400px breakpointok, hamburger menü
- **PWA manifest** — telepíthető app Android (Chrome) és iPhone (Safari) eszközökre
- **Favicon-csomag** — multi-size `.ico`, 32px PNG, 180px apple-touch-icon
- **Használati útmutató** — telepítési leírással Android/iPhone-ra

## Tech stack

| Réteg | Technológia |
|-------|-------------|
| Backend | Python 3 / Flask 3.1 |
| Adatbázis | PostgreSQL (psycopg2, connection pool) |
| AI | OpenAI GPT-4o-mini API |
| Email | Brevo (Sendinblue) API |
| Frontend | HTML/CSS/JS, Leaflet térkép |
| Szerver | Gunicorn + Nginx reverse proxy |
| CDN / proxy | Cloudflare (TLS, cache, AI bot management) |
| Auth | Flask-Login, Flask-WTF (CSRF), bcrypt |
| Push | Web Push API (VAPID), Service Worker |

## Biztonsági fejlécek

Az alkalmazás minden válaszra beállítja:

- `Content-Security-Policy` — `default-src 'self'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`
- `Strict-Transport-Security` — `max-age=31536000; includeSubDomains` (HTTPS-en)
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(self), camera=(), microphone=(), payment=()`

## Telepítés

### Automatikus (Debian/Ubuntu)

```bash
bash install.sh
```

Ez beállítja a teljes stacket: PostgreSQL, Python venv, systemd service, Nginx, UFW tűzfal, napi DB backup cron.

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

3. Másold és töltsd ki a `.env` fájlt (részleteket lásd a [`.env.example`](.env.example)-ben):
   ```bash
   cp .env.example .env
   nano .env
   ```

   **Kötelező változók** (ha hiányoznak, az app nem indul):
   - `FLASK_SECRET_KEY` — session titkosítás (generálás: `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `DATABASE_URL` — PostgreSQL connection string

   **Funkciókhoz kapcsolódó változók:**
   - `OPENAI_API_KEY` — GPT-4o-mini (AI kategorizálás nélkül is fut, csak "other" kategória lesz)
   - `BREVO_API_KEY` + `BREVO_SENDER_EMAIL` + `BREVO_SENDER_NAME` — Brevo email (jelszó-reset + admin alert nélkül nem küld email)
   - `VAPID_PUBLIC_KEY` + `VAPID_PRIVATE_KEY` + `VAPID_EMAIL` — Web Push értesítések
   - `ADMIN_ALERT_EMAIL` — gyanús esemény riasztás célcíme
   - `SITE_URL` — kanonikus URL (default: `https://zeghangja.hu`) — sitemap, canonical, OG URL forrása
   - `UPLOAD_DIR`, `MAX_UPLOAD_MB` — fotó feltöltés

4. VAPID kulcsok generálása (push értesítésekhez):
   ```bash
   bash setup-vapid.sh
   ```

5. Indítsd el:
   ```bash
   flask run
   ```

## Facebook auto-poster setup

A 20 percenként futó `fb_autopost.py` cron a saját Facebook Page-re posztol AI által kiválasztott helyi hírt (csak `category='local'`, 07:00–22:00 Europe/Budapest, napi max 8). A link az 1. komment-be kerül (FB algoritmus link-penalty miatt).

A Page ID-t és a Page Access Token-t **az admin felületen** lehet beállítani — DB-ben titkosítva tárolódik (Fernet, lásd "Secret tárolás" alább), nem .env-ben.

### Beállítás (egyszeri, ~5 perc)

1. **Admin felület**: jelentkezz be admin user-rel → `Admin → Integrációk` (`/admin/integraciok`).
2. **Wizard használata** (ha nincs még long-lived Page Access Token-ed):
   - Graph API Explorerben generálj User Token-t MIND A 4 permissionnel: `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, **`pages_manage_engagement`** (utóbbi a Page-saját-kommenteléshez kell — link az 1. kommentben!)
   - Nyisd ki a "Long-lived Page Access Token előállítás (wizard)" panelt
   - Töltsd ki az App ID, App Secret és Short User Token mezőket (a wizard részletes lépéseket ad)
   - Submit → a szerver kicseréli long-lived-re, lekéri a Page-eket, és (ha csak 1 van) automatikusan elmenti
3. **Vagy manuális mód** (ha már van Page Access Token-ed):
   - Nyisd ki a "Manuális token mentés" panelt
   - Page ID + Page Access Token mezőket töltsd ki → Mentés
4. **Token tesztelése**: a "Token tesztelése" gomb ellenőrzi a tárolt tokent (GET /me hívás).
5. **Cron telepítés** (csak egyszer szerveren):
   ```bash
   (crontab -u zeghang -l 2>/dev/null | grep -v fb_autopost; \
    echo "*/20 7-22 * * * /opt/zeghang/venv/bin/python /opt/zeghang/fb_autopost.py >> /opt/zeghang/fb_autopost.log 2>&1") \
    | crontab -u zeghang -
   ```

A `FB_AUTOPOST_MAX_PER_DAY=8` és `FB_CANDIDATE_WINDOW_MIN=360` env változókkal hangolható a posztlimit és a friss-cikk ablak.

### Token rotáció

A long-lived Page Access Token "soha nem jár le" — amíg a Facebook nem kényszerít újra-engedélyezést, vagy nem váltasz jelszót. Ha 401-et adna, ismételd meg az admin wizardot.

## Secret tárolás (encryption-at-rest)

A `lib/secrets.py` modul Fernet-titkosítással (cryptography lib) tárolja az érzékeny kulcsokat a DB-ben (`app_secrets` tábla). Jelenleg ide tartozik:
- `facebook.page_id`, `facebook.page_access_token`

A titkosítási kulcs:
- **Preferált**: `SETTINGS_ENCRYPTION_KEY` env változó (Fernet-formátum, 44-char base64). Generálás:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- **Fallback**: ha az env üres, a `FLASK_SECRET_KEY`-ből PBKDF2-vel származtatódik. Production-ban érdemes saját `SETTINGS_ENCRYPTION_KEY`-t adni, hogy a `FLASK_SECRET_KEY` rotáció ne tegye olvashatatlanná a tárolt secret-eket.

`.env` fallback: ha a DB-ben üres egy kulcs, a `get_secret()` még megpróbálja a megadott env változót (kompatibilitási réteg a meglévő `.env`-es deployhoz). Új deploynál ezeket NE töltsd a `.env`-be, hanem admin felületen.

## Deploy és frissítés

A szerveren:

```bash
cd /opt/zeghang && git pull && systemctl restart zeghang
```

A cache-busting miatt a CSS/JS automatikusan friss hash-t kap (`?v=<commit>`), nem kell manuális Cloudflare purge.

## Backup és disaster recovery

- **Proxmox CT backup** — napi 01:00, snapshot mode (directory storage-en suspend-re fallback-el, ~1-5 mp downtime, PG konzisztens)
- **PostgreSQL pg_dump** — napi 03:00 cron (`backup.sh`), 7 napos rotáció, `/opt/zeghang/backups/zeghang_YYYYMMDD_HHMMSS.sql.gz`

### Restore procedure (2026-04-18-kor tesztelve)

```bash
# Teszt DB-be vissza:
sudo -u postgres createdb zeghang_restore_test
sudo -u postgres bash -c "gunzip -c /opt/zeghang/backups/zeghang_YYYYMMDD.sql.gz | psql -d zeghang_restore_test"
sudo -u postgres psql -d zeghang_restore_test -c "\dt"

# Éles DB visszaállítása (ÓVATOSAN — felülírja):
systemctl stop zeghang
sudo -u postgres dropdb zeghang && sudo -u postgres createdb -O zeghang zeghang
sudo -u postgres bash -c "gunzip -c /opt/zeghang/backups/zeghang_YYYYMMDD.sql.gz | psql -d zeghang"
systemctl start zeghang
```

## Projektstruktúra

```
├── app.py                    # Flask alkalmazás, összes route (~2200 sor)
├── lib/
│   ├── ai.py                 # OpenAI integráció (kategorizálás, duplikáció, sürgősség), prompt injection védelemmel
│   ├── config.py             # Környezeti változók (FLASK_SECRET_KEY fail-fast, SITE_URL)
│   ├── database.py           # PostgreSQL connection pool, migrációk
│   ├── email.py              # Brevo email küldés
│   ├── moderation.py         # Trágárságszűrő
│   └── notifications.py      # Web push értesítések
├── templates/
│   ├── admin/                # Admin felület sablonok (pagination)
│   ├── base.html             # Publikus oldal alap (SEO meta, JSON-LD, favicon)
│   ├── app_base.html         # Bejelentkezett felület alap (noindex)
│   ├── dashboard.html        # Áttekintő (fő felület)
│   ├── guide.html            # Használati útmutató
│   ├── privacy.html          # GDPR adatvédelmi tájékoztató
│   ├── terms.html            # ÁSZF
│   ├── settings.html         # Felhasználói beállítások
│   └── ...
├── static/
│   ├── css/style.css         # Stíluslap (responsive)
│   ├── js/app.js             # Frontend JS (cookie consent, password toggle, theme, AI autocomplete)
│   ├── sw.js                 # Service Worker (push)
│   ├── manifest.json         # PWA manifest
│   ├── favicon.ico           # Multi-size favicon
│   ├── favicon-32.png        # Modern böngésző favicon
│   ├── apple-touch-icon.png  # iOS home screen ikon
│   ├── og-image.png          # 1200×630 social preview
│   ├── icon-192.png          # PWA ikon
│   ├── icon-512.png          # PWA ikon
│   └── districts.geojson     # Körzeti térképadatok
├── install.sh                # Automatikus telepítő script
├── setup-vapid.sh            # VAPID kulcs generáló
├── backup.sh                 # PostgreSQL napi dump
├── requirements.txt          # Python függőségek
└── .env.example              # Konfiguráció minta
```

## Licensz

Open source. A forráskód nyilvánosan elérhető és auditálható a GitHubon: [gaberun24/zeghang](https://github.com/gaberun24/zeghang).

---

*Készítette: Hájas Gábor · Zalaegerszeg · 2026*
