#!/bin/bash
# ============================================================
# ZEG Hang — Teljes telepítő script (Debian/Ubuntu szűz CT)
# Futtatás: curl -sSL <url> | bash   VAGY   bash install.sh
# ============================================================

set -euo pipefail

APP_USER="zeghang"
APP_DIR="/opt/zeghang"
REPO="https://github.com/gaberun24/zeghang.git"
DB_NAME="zeghang"
DB_USER="zeghang"
DB_PASS=$(openssl rand -hex 16)
FLASK_SECRET=$(openssl rand -hex 32)
DOMAIN="zeghang.hajasgabor.com"

echo "========================================="
echo " ZEG Hang — Telepítés indul"
echo "========================================="

# ── 1. Rendszer frissítés + alapcsomagok ──
echo "[1/9] Rendszer frissítés..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    git curl wget nano \
    python3 python3-pip python3-venv \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    build-essential libpq-dev \
    ufw

# ── 2. Felhasználó létrehozása ──
echo "[2/9] Felhasználó: ${APP_USER}..."
if ! id -u "$APP_USER" &>/dev/null; then
    useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER"
fi

# ── 3. PostgreSQL ──
echo "[3/9] PostgreSQL beállítás..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

# Set timezone
sudo -u postgres psql -d "$DB_NAME" -c "ALTER DATABASE ${DB_NAME} SET timezone TO 'Europe/Budapest';"

echo "  DB: ${DB_NAME} / User: ${DB_USER} / Pass: ${DB_PASS}"

# ── 4. Alkalmazás klónozása ──
echo "[4/9] Repo klónozás → ${APP_DIR}..."
if [ -d "${APP_DIR}/.git" ]; then
    cd "$APP_DIR"
    git pull origin main
else
    git clone "$REPO" "$APP_DIR"
fi

cd "$APP_DIR"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# ── 5. Python venv + dependencies ──
echo "[5/9] Python venv + pip install..."
sudo -u "$APP_USER" python3 -m venv "${APP_DIR}/venv"
sudo -u "$APP_USER" "${APP_DIR}/venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

# ── 6. .env fájl ──
echo "[6/9] .env konfiguráció..."
cat > "${APP_DIR}/.env" <<ENVEOF
# Flask
FLASK_SECRET_KEY=${FLASK_SECRET}
FLASK_DEBUG=0

# PostgreSQL
DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}

# OpenAI — cseréld ki a saját API kulcsodra!
OPENAI_API_KEY=sk-CHANGEME
OPENAI_MODEL=gpt-4o-mini

# Upload
UPLOAD_DIR=${APP_DIR}/uploads
MAX_UPLOAD_MB=20
ENVEOF

chown "$APP_USER":"$APP_USER" "${APP_DIR}/.env"
chmod 600 "${APP_DIR}/.env"

# Upload dir
mkdir -p "${APP_DIR}/uploads"
chown "$APP_USER":"$APP_USER" "${APP_DIR}/uploads"

# Flask sessions dir
mkdir -p "${APP_DIR}/flask_sessions"
chown "$APP_USER":"$APP_USER" "${APP_DIR}/flask_sessions"

# ── 7. Systemd service ──
echo "[7/9] Systemd service..."
cat > /etc/systemd/system/zeghang.service <<SVCEOF
[Unit]
Description=ZEG Hang — Zalaegerszeg Közösségi Platform
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/venv/bin:/usr/bin
ExecStart=${APP_DIR}/venv/bin/gunicorn \
    --bind 127.0.0.1:5000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile ${APP_DIR}/access.log \
    --error-logfile ${APP_DIR}/error.log \
    app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# Install gunicorn
sudo -u "$APP_USER" "${APP_DIR}/venv/bin/pip" install gunicorn -q

systemctl daemon-reload
systemctl enable zeghang
systemctl start zeghang

echo "  Service elindult: systemctl status zeghang"

# ── 8. Nginx reverse proxy ──
echo "[8/9] Nginx konfiguráció..."
cat > /etc/nginx/sites-available/zeghang <<NGXEOF
server {
    listen 80;
    server_name ${DOMAIN};

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        alias ${APP_DIR}/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /uploads/ {
        alias ${APP_DIR}/uploads/;
        expires 7d;
    }
}
NGXEOF

ln -sf /etc/nginx/sites-available/zeghang /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl reload nginx
echo "  Nginx konfigurálva: ${DOMAIN}"

# ── 9. Tűzfal ──
echo "[9/9] UFW tűzfal..."
ufw --force enable
ufw allow ssh
ufw allow 'Nginx Full'

echo ""
echo "========================================="
echo " TELEPÍTÉS KÉSZ!"
echo "========================================="
echo ""
echo " App:      http://${DOMAIN}"
echo " Dir:      ${APP_DIR}"
echo " DB:       ${DB_NAME} / ${DB_USER} / ${DB_PASS}"
echo " Service:  systemctl status zeghang"
echo " Logok:    ${APP_DIR}/access.log  |  ${APP_DIR}/error.log"
echo ""
echo " TEENDŐK:"
echo " 1. Írd be az OpenAI API kulcsodat:"
echo "    nano ${APP_DIR}/.env"
echo ""
echo " 2. Cloudflare Tunnel beállítás (később):"
echo "    cloudflared tunnel --url http://localhost:5000"
echo ""
echo " 3. Szolgáltatás újraindítás .env módosítás után:"
echo "    systemctl restart zeghang"
echo ""
echo " 4. Frissítés GitHub-ról:"
echo "    cd ${APP_DIR} && git pull && systemctl restart zeghang"
echo ""
echo "========================================="
