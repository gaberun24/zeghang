# Zalaegerszeg Hangja — Projekt állapot

Utolsó frissítés: 2026. március 27.

---

## Kész funkciók

| Funkció | Állapot | Megjegyzés |
|---------|---------|------------|
| Probléma bejelentés (cím, leírás, kategória, fotó) | ✅ Kész | Működik |
| AI kategorizálás (GPT-4o-mini) | ✅ Kész | Automatikus javaslat, felülírható |
| AI sürgősség-értékelés | ✅ Kész | 4 fokozat |
| AI duplikátum-felismerés | ✅ Kész | Megmutatja a hasonló bejelentést |
| AI tartalomszűrés | ✅ Kész | Nem közterületi panaszok kiszűrése |
| Szavazás (👍/👎) | ✅ Kész | Anonim, körzeti arányosítás |
| 12 választókerület + térkép | ✅ Kész | GeoJSON + Leaflet |
| Áttekintő (körzeti statisztikák) | ✅ Kész | Toplista, aktivitás |
| Trágárságszűrő | ✅ Kész | Magyar csúnyaszó-lista, automatikus csillagozás |
| Admin felület | ✅ Kész | Bejelentések/userek/kommentek kezelése |
| Cookie consent + 112 figyelmeztetés | ✅ Kész | localStorage/sessionStorage |
| Mobil responsive | ✅ Kész | 3 breakpoint, hamburger menü |
| PWA manifest + ikonok | ✅ Kész | Telepíthető appként |
| Reputációs rendszer | ✅ Kész | Pontok, szintek, jelvények |
| Push értesítések | ✅ Kész | Web Push API, felhasználói beállítások |
| Elfelejtett jelszó | ✅ Kész | Brevo email API |
| Címmódosítás (évi 1x) | ✅ Kész | Beállítások oldalon |
| Beállítások oldal | ✅ Kész | Név, cím, értesítések |
| Közösségi megoldás-szavazás | ✅ Kész | 7 napos szavazás, automatikus státuszváltás |
| Troll védelem (shadowban + rate limit) | ✅ Kész | Reputáció-alapú |
| Utca-autocomplete bejelentésnél | ✅ Kész | Zalaegerszegi utcanevek |
| Használati útmutató | ✅ Kész | Telepítési leírás Android/iPhone |
| Magyarítás (Dashboard → Áttekintő) | ✅ Kész | Angol kifejezések eltávolítva |
| Footer nonprofit szöveg | ✅ Kész | Minden oldalon |
| Sérülékenység javítások | ✅ Kész | XSS, rate limit, CSRF, session, stb. |

## Tervezett / jövőbeli funkciók

| Funkció | Prioritás | Megjegyzés |
|---------|-----------|------------|
| Facebook auto-posztolás | 🔵 Alacsony | Napi összefoglaló poszt automatikusan |
| Statisztika export (CSV) | 🔵 Alacsony | Admin funkció |
| Több nyelv támogatás | 🔵 Alacsony | Jelenleg csak magyar |

## Ismert problémák

Jelenleg nincs ismert probléma.

## Szerver

- **Élő oldal:** zeghang.hajasgabor.com
- **Szerver:** /opt/zeghang (Debian/Ubuntu)
- **Deploy:** `git pull && systemctl restart zeghang`
- **Service:** zeghang.service (Gunicorn)

---

*Projekt indulás: 2026. március · Készítette: Hajas Gábor*
