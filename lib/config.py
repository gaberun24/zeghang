import os
from dotenv import load_dotenv

# Load .env — production first, fallback to local
for _env_path in ["/opt/zeghang/.env", ".env"]:
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)

# Flask
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
if not FLASK_SECRET_KEY:
    raise RuntimeError(
        "FLASK_SECRET_KEY nincs beállítva a .env-ben. "
        "Session stabilitás (különösen multi-worker Gunicornnál) csak explicit, "
        "perzisztens kulccsal garantálható. Generálás: `python -c \"import secrets; print(secrets.token_hex(32))\"`"
    )
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeghang:password@localhost:5432/zeghang")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Upload
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "static/uploads")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))

# Brevo (email)
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "zeghangja@proton.me")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Zalaegerszeg Hangja")

# Web Push (VAPID)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "zeghangja@proton.me")

# Admin alerts
ADMIN_ALERT_EMAIL = os.getenv("ADMIN_ALERT_EMAIL", "")

# Canonical site URL — ezt használjuk sitemap, canonical, og:url, og:image abszolút
# URL-ekhez. Ne bízzunk a request.host_url-re, mert Cloudflare Flexible SSL mögött
# rosszul (http://) jön vissza. Env override: SITE_URL.
SITE_URL = os.getenv("SITE_URL", "https://zeghangja.hu").rstrip("/")

# Facebook Page auto-poster — graph.facebook.com posztoláshoz a saját Page-re.
# A token long-lived Page Access Token (lásd README "Facebook auto-poster" setup).
# Üres tokennel az fb_autopost.py no-op módban fut.
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
FB_AUTOPOST_MAX_PER_DAY = int(os.getenv("FB_AUTOPOST_MAX_PER_DAY", "8"))
# Mennyi percre visszamenőleg fogadunk el "friss" cikket FB posztra (fetched_at alapján).
# Default 360 perc (6 óra): jó kompromisszum a "friss érzet" és a kandidat-pool között.
# Ha a Google News pörögteti az új zalaegerszegi híreket, csökkenthető (pl. 90 perc).
FB_CANDIDATE_WINDOW_MIN = int(os.getenv("FB_CANDIDATE_WINDOW_MIN", "360"))
