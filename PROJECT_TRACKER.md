# Zalaegerszeg Hangja — Projekt állapot

Utolsó frissítés: 2026. április 18. — **rollout napja**

---

## Kész funkciók

### Alapplatform
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Probléma bejelentés (cím, leírás, kategória, fotó) | ✅ Kész | Utca-autocomplete, GPS opcionális |
| Szavazás (👍/👎) | ✅ Kész | Anonim, körzeti arányosítás, thumb ikonok |
| 12 választókerület + térkép | ✅ Kész | GeoJSON + Leaflet |
| Áttekintő (körzeti statisztikák) | ✅ Kész | Toplista, aktivitás |
| Közösségi megoldás-szavazás | ✅ Kész | 7 napos szavazás, automatikus státuszváltás |
| Hozzászólások | ✅ Kész | Moderálható admin felületen |

### AI funkciók
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| AI kategorizálás (GPT-4o-mini) | ✅ Kész | Automatikus javaslat, felülírható |
| AI sürgősség-értékelés | ✅ Kész | 4 fokozat |
| AI duplikátum-felismerés | ✅ Kész | Összeveti 50 nyitott bejelentéssel |
| AI tartalomszűrés | ✅ Kész | Nem közterületi panaszok kiszűrése |
| AI autocomplete gépelés közben | ✅ Kész | Kategória javaslat cím alapján |
| AI prompt injection védelem | ✅ Kész | System message + JSON payload |

### Biztonság és GDPR
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Teljes biztonsági audit + javítások | ✅ Kész | 2026-04-18, 10 finding (1 CRITICAL, 3 HIGH, 5 MEDIUM, 2 LOW) kijavítva |
| GDPR-megfelelő adatvédelmi tájékoztató | ✅ Kész | 16 szekció, jogalap-tábla, Art. 22 (automatizált döntéshozatal), NAIH |
| Cookie consent (granuláris, visszavonható) | ✅ Kész | Verziózott JSON localStorage, footer link, privacy oldal gomb |
| 18+ életkor ellenőrzés | ✅ Kész | Születési dátum alapján, **nem tárolva** |
| Jelszó megjelenítés toggle | ✅ Kész | Login, register, reset_password oldalakon |
| CSRF védelem | ✅ Kész | Flask-WTF globális, JSON POST X-CSRFToken |
| Rate limit — login, register, password reset | ✅ Kész | IP-alapú, security_log-ban |
| HSTS + keményített CSP | ✅ Kész | frame-ancestors 'none', Permissions-Policy |
| Email log SHA-256 hash (GDPR) | ✅ Kész | login/register/password_reset details-ben |
| Session.clear logoutkor | ✅ Kész | Session fixation védelem |
| Admin pagination | ✅ Kész | users, comments, issues — 30/oldal |
| Pillow zip-bomb védelem | ✅ Kész | MAX_IMAGE_PIXELS=50M + explicit exception |
| Path traversal safety-belt | ✅ Kész | realpath prefix check fájlmentéskor |
| Admin referrer whitelist | ✅ Kész | Csak /admin/* redirect engedélyezett |
| Trágárságszűrő | ✅ Kész | Magyar csúnyaszó-lista, automatikus csillagozás |
| Troll védelem (shadowban + rate limit) | ✅ Kész | Reputáció-alapú |
| FLASK_SECRET_KEY fail-fast | ✅ Kész | Nincs fallback, hiányzik → RuntimeError |

### Admin felület
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Admin felület | ✅ Kész | Bejelentések/userek/kommentek kezelése |
| Admin statisztikák | ✅ Kész | Látogatottság, kategóriák, körzeti aktivitás |
| Admin rendszer állapot (health) | ✅ Kész | CPU, memória, HDD, uptime |
| Biztonsági napló (admin) | ✅ Kész | Sikertelen login, tiltott hozzáférés, admin műveletek |
| Email riasztások (Brevo) | ✅ Kész | Gyanús tevékenység értesítés adminnak |

### Felhasználói funkciók
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Reputációs rendszer | ✅ Kész | Pontok, szintek, jelvények |
| Push értesítések | ✅ Kész | Web Push API, felhasználói beállítások |
| Elfelejtett jelszó | ✅ Kész | Brevo email API, 1 órás token |
| Címmódosítás (évi 1x) | ✅ Kész | Beállítások oldalon |
| Beállítások oldal | ✅ Kész | Név, cím, értesítések, téma |
| Használati útmutató | ✅ Kész | Telepítési leírás Android/iPhone |

### SEO és infrastruktúra
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| SEO meta tagek (description, OG, Twitter) | ✅ Kész | Oldalspecifikus description block |
| Canonical URL | ✅ Kész | SITE_URL alapú |
| Schema.org JSON-LD | ✅ Kész | Organization + WebSite |
| og-image.png (1200×630) | ✅ Kész | Social preview |
| /robots.txt + /sitemap.xml | ✅ Kész | Cloudflare Managed robots.txt-vel kombinálva |
| Favicon csomag | ✅ Kész | .ico multi-size + 32px PNG + apple-touch-icon |
| Google Search Console | ✅ Kész | zeghangja.hu domain property verifikálva |
| Cache-busting | ✅ Kész | url_for('static', ...) automatikus ?v=<commit-hash> |
| HTTPS SITE_URL canonical | ✅ Kész | Cloudflare Flexible SSL mögött is biztos HTTPS |
| Domain: zeghangja.hu | ✅ Kész | Korábbi zeghang.hajasgabor.com-ról átállva |

### Megjelenés
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Sötét/világos téma | ✅ Kész | Rendszerfüggő + kézi váltás beállításokban |
| Nap/Hold animáció | ✅ Kész | Valós idejű égitest a hero szekcióban |
| Szavazás 👍/👎 ikonok | ✅ Kész | Thumb ikonok |
| Mobil responsive | ✅ Kész | 3 breakpoint, hamburger menü |
| PWA manifest + ikonok | ✅ Kész | Telepíthető appként |
| Footer nonprofit szöveg | ✅ Kész | Minden oldalon |
| Magyarítás (Dashboard → Áttekintő) | ✅ Kész | Angol kifejezések eltávolítva |

### Backup és disaster recovery
| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Proxmox CT backup (napi 01:00) | ✅ Kész | Snapshot mode, UNAS_Backup storage |
| PostgreSQL pg_dump (napi 03:00) | ✅ Kész | 7 napos rotáció, /opt/zeghang/backups/ |
| Disaster recovery dokumentálva | ✅ Kész | README, 2026-04-18 restore-teszt OK (10/10 tábla) |

## Fejlesztés alatt 🔧

| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| SVG sziluettek (TV torony, nagytemplom) | 🟠 Folyamatban | Kézzel rajzolt SVG a hero tájba |
| Időjárás effektek | 🟠 Folyamatban | Eső, hó, felhők, köd, villámlás CSS animáció |
| OpenWeatherMap API integráció | 🟠 Folyamatban | Zalaegerszeg valós idejű időjárás a hero-ban |

## Tervezett / jövőbeli funkciók

| Funkció | Prioritás | Megjegyzés |
|---------|-----------|------------|
| Strict CSP — onclick→addEventListener refactor | 🟡 Közepes | M3 finding az auditból, `'unsafe-inline'` kivétele |
| Email verifikáció regisztrációnál | 🟡 Közepes | email_verified_at oszlop + verify token flow |
| Képviselői válasz funkció | 🟡 Közepes | Képviselők reagálhatnak a bejelentésekre |
| Facebook auto-posztolás | 🔵 Alacsony | Napi összefoglaló poszt automatikusan |
| Statisztika export (CSV) | 🔵 Alacsony | Admin funkció |
| Cookie banner stílus javítás | 🔵 Alacsony | Mobilon kisebb finomítás |

## Ismert problémák

Jelenleg nincs ismert, reprodukálható probléma.

## Szerver

- **Élő oldal:** zeghangja.hu (Cloudflare proxy + TLS, Nginx reverse proxy, Gunicorn)
- **Szerver:** /opt/zeghang (Debian/Ubuntu LXC container a Proxmox-on, CTID 666)
- **Deploy:** `cd /opt/zeghang && git pull && systemctl restart zeghang`
- **Service:** zeghang.service (Gunicorn)
- **Backup:** Proxmox napi 01:00 (CT snapshot) + pg_dump napi 03:00

---

*Projekt indulás: 2026. március · Rollout: 2026. április 18. · Készítette: Hajas Gábor*
