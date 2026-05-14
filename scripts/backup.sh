#!/bin/bash
# Database backup script for FAIRDatabase demo

set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/fairdatabase_backup_${TIMESTAMP}.sql"

# PostgreSQL connection parameters
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDB="${POSTGRES_DB:-postgres}"
PGUSER="${POSTGRES_USER:-postgres}"

mkdir -p "$BACKUP_DIR"

echo "Starting backup to $BACKUP_FILE..."

# Export PGPASSWORD for pg_dump
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Backup demo schema only (for privacy)
pg_dump \
    --host="$PGHOST" \
    --port="$PGPORT" \
    --username="$PGUSER" \
    --dbname="$PGDB" \
    --schema=_demo \
    --format=custom \
    --file="${BACKUP_FILE%.sql}.dump"

# Also export as plain SQL for easy restoration
pg_dump \
    --host="$PGHOST" \
    --port="$PGPORT" \
    --username="$PGUSER" \
    --dbname="$PGDB" \
    --schema=_demo \
    --format=plain \
    --file="$BACKUP_FILE"

# Compress
gzip "$BACKUP_FILE"
gzip "${BACKUP_FILE%.sql}.dump"

echo "Backup completed: ${BACKUP_FILE}.gz"

# Keep only last 7 days of backups
find "$BACKUP_DIR" -name "fairdatabase_backup_*.sql.gz" -mtime +7 -delete

echo "Old backups cleaned up"