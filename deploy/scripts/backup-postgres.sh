#!/bin/bash
set -Eeuo pipefail
umask 077

backup_dir="${BACKUP_DIR:-/var/backups/key-writer}"
retention_days="${BACKUP_RETENTION_DAYS:-21}"
pg_service="${BACKUP_PG_SERVICE:-key_writer}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_path="${backup_dir}/key_writer_${timestamp}.dump"

: "${PGSERVICEFILE:=/etc/key-writer/pg_service.conf}"
: "${PGPASSFILE:=/etc/key-writer/pgpass}"
export PGSERVICEFILE PGPASSFILE

if ! [[ "${retention_days}" =~ ^[0-9]+$ ]] || (( retention_days < 1 || retention_days > 365 )); then
    echo "Backup failed: BACKUP_RETENTION_DAYS must be between 1 and 365" >&2
    exit 2
fi

mkdir -p "${backup_dir}"
chmod 0700 "${backup_dir}"

exec 9>"${backup_dir}/.backup.lock"
if ! flock -n 9; then
    echo "Backup skipped: another backup is already running" >&2
    exit 1
fi

partial_path="$(mktemp "${backup_dir}/.partial_${timestamp}_XXXXXX")"
cleanup() {
    rm -f -- "${partial_path}"
}
trap cleanup EXIT

pg_dump \
    --dbname="service=${pg_service}" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-acl \
    --file="${partial_path}"

# A custom dump is accepted only when PostgreSQL can read its catalogue.
pg_restore --list "${partial_path}" >/dev/null
chmod 0600 "${partial_path}"
mv -- "${partial_path}" "${final_path}"
trap - EXIT

find "${backup_dir}" -maxdepth 1 -type f -name 'key_writer_*.dump' \
    -mtime "+${retention_days}" -delete

echo "Backup completed and verified: ${final_path}"
