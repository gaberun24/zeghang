# Security Policy — Zalaegerszeg Hangja

> English summary at the bottom.

## Támogatott verziók

Ez egy folyamatosan üzemelő, élő platform ([zeghangja.hu](https://zeghangja.hu)). Biztonsági javítások kizárólag a `main` ág legfrissebb állapotára készülnek.

| Verzió | Támogatott |
|--------|------------|
| `main` (éles) | ✅ Igen |
| Régebbi commitok | ❌ Nem |

## Biztonsági sebezhetőség bejelentése

Ha biztonsági hibát (XSS, injekció, jogosultság-eszkaláció, CSRF-bypass, adatvédelmi incidenst stb.) találtál, **kérjük NE nyiss publikus GitHub issue-t** — ez a hibát azonnal nyilvánossá tenné, mielőtt javítani tudnánk.

**Küldj e-mailt:**
**[zeghangja@proton.me](mailto:zeghangja@proton.me?subject=Security%20%E2%80%94%20Zalaegerszeg%20Hangja)**

Ha lehet, a tárgyban szerepeljen „Security”. Az üzenet tartalmazhat:
- Rövid leírás (mi a probléma)
- Reprodukciós lépések / PoC (kérjük minimalizálva)
- Az érintett komponens (URL, fájl, route)
- Javasolt enyhítés, ha van ötleted

## Mit vállalunk
- **72 órán belül** visszaigazolást küldünk, hogy megkaptuk a bejelentést
- **Magas és kritikus súlyosság**: 7 napon belül javítás + szerveren deploy
- **Közepes/alacsony**: ~30 napon belül
- Egyetértés esetén **nyilvános elismerés** (credit) a commit üzenetben és ebben a dokumentumban (opcionálisan, ha kéred)

## Safe harbor — jogi keretek

Amennyiben a jóhiszemű biztonsági kutatás az alábbi kereteken belül zajlik, polgári vagy büntetőjogi lépést nem kezdeményezünk:

- **Ne okozz szolgáltatáskiesést** (DoS, load-tesztelés), ne módosíts vagy semmisíts meg adatot
- **Ne érj el mások személyes adatát** — ha véletlen hozzáféréshez jutsz, azonnal abbahagyod és törlöd
- **Ne használd ki** a hibát a bejelentésen túlmenően
- **Legalább 90 napig** adj időt a javításra a publikálás előtt (responsible disclosure)
- A jóhiszemű tesztelésre saját fiókod használd, ne máséit

## Ami nem tartozik ide

Ne biztonsági bejelentést, hanem **sima kapcsolattartást** használj az alábbiakhoz:

- Általános fejlesztési ötletek → [Kapcsolat oldal](https://zeghangja.hu/kapcsolat)
- UI/UX javaslatok → publikus [GitHub issue](https://github.com/gaberun24/zeghang/issues)
- Adatkezelési kérelmek (GDPR érintetti jogok) → [Adatvédelmi tájékoztató](https://zeghangja.hu/adatvedelem)

## Scope — mit vizsgálhatsz

- `zeghangja.hu` és minden `*.zeghangja.hu` aldomain
- Ez a GitHub repozitórium kódja
- A `lib/`, `templates/`, `static/`, `app.py` és `install.sh` fájlok

## Scope-on kívül

- Harmadik fél szolgáltatók (Cloudflare, Brevo, OpenAI) — ezeket a szolgáltatóknak közvetlenül jelentsd
- A szerver operációs rendszer / Proxmox infrastruktúra

---

## English summary

If you find a security vulnerability in this civic tech platform (source: [gaberun24/zeghang](https://github.com/gaberun24/zeghang), live at [zeghangja.hu](https://zeghangja.hu)), **please do not open a public GitHub issue**. Email us at [zeghangja@proton.me](mailto:zeghangja@proton.me?subject=Security%20report) instead.

We'll acknowledge within 72 hours; high/critical severity patched within 7 days. Good-faith research is welcome and won't lead to legal action if you avoid service disruption, don't access other users' data, and follow responsible disclosure (90-day grace period).

For non-security suggestions, use the [contact page](https://zeghangja.hu/kapcsolat) or open a public GitHub issue.
