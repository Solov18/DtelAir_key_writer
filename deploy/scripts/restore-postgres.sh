#!/bin/bash
set -Eeuo pipefail
umask 077

dump_path=""
confirmation=""
skip_safety_backup=false
while (($#)); do
    case "$1" in
        --dump) dump_path="${2:-}"; shift 2 ;;
        --confirm) confirmation="${2:-}"; shift 2 ;;
        --skip-safety-backup) skip_safety_backup=true; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "${dump_path}" || ! -f "${dump_path}" ]]; then
    echo "Usage: restore-postgres.sh --dump /path/file.dump --confirm DATABASE [--skip-safety-backup]" >&2
    exit 2
fi

pg_service="${BACKUP_PG_SERVICE:-key_writer}"
: "${PGSERVICEFILE:=/etc/key-writer/pg_service.conf}"
: "${PGPASSFILE:=/etc/key-writer/pgpass}"
export PGSERVICEFILE PGPASSFILE

database_name="$(psql "service=${pg_service}" --no-psqlrc -Atqc 'SELECT current_database()')"
if [[ "${confirmation}" != "${database_name}" ]]; then
    echo "Restore refused: pass --confirm ${database_name}" >&2
    exit 3
fi

pg_restore --list "${dump_path}" >/dev/null

if [[ "${skip_safety_backup}" != true ]]; then
    "$(dirname "$0")/backup-postgres.sh"
fi

pg_restore \
    --dbname="service=${pg_service}" \
    --clean \
    --if-exists \
    --no-owner \
    --no-acl \
    --exit-on-error \
    --single-transaction \
    "${dump_path}"

echo "Restore completed: database=${database_name} dump=${dump_path}"
