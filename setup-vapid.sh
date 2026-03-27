#!/bin/bash
# ============================================================
# VAPID kulcsok generálása és .env-be illesztése
# Futtatás: bash setup-vapid.sh
# ============================================================

set -euo pipefail

APP_DIR="/opt/zeghang"
ENV_FILE="${APP_DIR}/.env"
VENV="${APP_DIR}/venv/bin"

# Check if already configured
if grep -q "VAPID_PUBLIC_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    echo "VAPID kulcsok már konfigurálva vannak a .env-ben."
    echo "Ha újra akarod generálni, előbb töröld a VAPID sorokat a .env-ből."
    exit 0
fi

# Install pywebpush if needed
echo "pywebpush telepítése..."
"${VENV}/pip" install pywebpush py-vapid -q

# Generate VAPID keys
echo "VAPID kulcsok generálása..."
VAPID_JSON=$("${VENV}/python3" << 'PYEOF'
import json, base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Generate key pair
private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

# Private key as PEM (single line for .env)
priv_pem = private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode().strip()

# Public key as urlsafe base64 (uncompressed point, 65 bytes)
pub_numbers = private_key.public_key().public_numbers()
x = pub_numbers.x.to_bytes(32, 'big')
y = pub_numbers.y.to_bytes(32, 'big')
pub_bytes = b'\x04' + x + y
pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()

print(json.dumps({"public": pub_b64, "private": priv_pem}))
PYEOF
)

VAPID_PUB=$(echo "$VAPID_JSON" | "${VENV}/python3" -c "import sys,json; print(json.load(sys.stdin)['public'])")
VAPID_PRIV_FILE="${APP_DIR}/vapid_private.pem"

# Save private key as PEM file
echo "$VAPID_JSON" | "${VENV}/python3" -c "import sys,json; print(json.load(sys.stdin)['private'])" > "$VAPID_PRIV_FILE"
chmod 600 "$VAPID_PRIV_FILE"

# Remove any existing empty VAPID lines
sed -i '/^VAPID_PUBLIC_KEY=$/d' "$ENV_FILE" 2>/dev/null || true
sed -i '/^VAPID_PRIVATE_KEY=$/d' "$ENV_FILE" 2>/dev/null || true
sed -i '/^VAPID_EMAIL=$/d' "$ENV_FILE" 2>/dev/null || true

# Append to .env
cat >> "$ENV_FILE" <<ENVEOF

# Web Push (VAPID) — automatikusan generálva $(date +%Y-%m-%d)
VAPID_PUBLIC_KEY=${VAPID_PUB}
VAPID_PRIVATE_KEY=${VAPID_PRIV_FILE}
VAPID_EMAIL=admin@zeghang.hu
ENVEOF

echo ""
echo "========================================="
echo " VAPID kulcsok sikeresen generálva!"
echo "========================================="
echo ""
echo " Public key:   ${VAPID_PUB}"
echo " Private key:  ${VAPID_PRIV_FILE}"
echo " .env frissítve: ${ENV_FILE}"
echo ""
echo " Indítsd újra a szolgáltatást:"
echo "   systemctl restart zeghang"
echo ""
