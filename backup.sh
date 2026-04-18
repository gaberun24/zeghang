#!/bin/bash
# ============================================================
# Zalaegerszeg Hangja — Napi PostgreSQL mentés
# Cron: 0 3 * * * /opt/zeghang/backup.sh
# ============================================================

set -euo pipefail

# Beállítások
APP_DIR="/opt/zeghang"
BACKUP_DIR="${APP_DIR}/backups"
DB_NAME="zeghang"
DB_USER="zeghang"
KEEP_DAYS=7

# .env-ből olvassuk a jelszót
if [ -f "${APP_DIR}/.env" ]; then
    DB_PASS=$(grep -oP 'DATABASE_URL=.*://[^:]+:\K[^@]+' "${APP_DIR}/.env" || true)
fi

if [ -z "${DB_PASS:-}" ]; then
    echo "[HIBA] Nem sikerült a DB jelszót kiolvasni a .env-ből"
    exit 1
fi

# Backup mappa
mkdir -p "$BACKUP_DIR"

# Fájlnév időbélyeggel
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/zeghang_${TIMESTAMP}.sql.gz"

# PostgreSQL dump + gzip tömörítés (history off az shell history mentes legyen)
set +o history 2>/dev/null || true
export PGPASSWORD="$DB_PASS"
pg_dump -h localhost -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"
unset PGPASSWORD
set -o history 2>/dev/null || true

# Uploads-ot NEM mentjük itt — a képek NAS-on tárolódnak, és a Proxmox CT backup
# amúgy is menti ami a CT-ben van. Ha valamikor visszakerülne a helyi uploads,
# a Proxmox snapshot úgyis befogja.

# Régi mentések törlése (KEEP_DAYS napnál régebbiek)
find "$BACKUP_DIR" -name "zeghang_*.sql.gz" -mtime +${KEEP_DAYS} -delete

# Méret kiírása
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[OK] Mentés kész: ${BACKUP_FILE} (${BACKUP_SIZE})"
