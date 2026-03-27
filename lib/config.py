import os
from dotenv import load_dotenv

# Load .env — production first, fallback to local
for _env_path in ["/opt/zeghang/.env", ".env"]:
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)

# Flask
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "")
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
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "noreply@zeghangja.hu")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Zalaegerszeg Hangja")

# Web Push (VAPID)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "admin@zeghang.hu")
