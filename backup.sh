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

# PostgreSQL dump + gzip tömörítés
export PGPASSWORD="$DB_PASS"
pg_dump -h localhost -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"
unset PGPASSWORD

# Uploads mappa mentése (csak ha van benne fájl)
UPLOADS_DIR="${APP_DIR}/uploads"
if [ -d "$UPLOADS_DIR" ] && [ "$(ls -A "$UPLOADS_DIR" 2>/dev/null)" ]; then
    UPLOADS_BACKUP="${BACKUP_DIR}/uploads_${TIMESTAMP}.tar.gz"
    tar -czf "$UPLOADS_BACKUP" -C "$APP_DIR" uploads/
    echo "[OK] Uploads mentve: ${UPLOADS_BACKUP}"
fi

# Régi mentések törlése (KEEP_DAYS napnál régebbiek)
find "$BACKUP_DIR" -name "zeghang_*.sql.gz" -mtime +${KEEP_DAYS} -delete
find "$BACKUP_DIR" -name "uploads_*.tar.gz" -mtime +${KEEP_DAYS} -delete

# Méret kiírása
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[OK] Mentés kész: ${BACKUP_FILE} (${BACKUP_SIZE})"
