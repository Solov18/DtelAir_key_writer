#!/bin/bash
set -Eeuo pipefail

cd /opt/key-writer

# The code/release must already have been copied into /opt/key-writer. A
# verified database backup is mandatory before dependency or schema changes.
systemctl start key-writer-backup.service
systemctl --quiet is-failed key-writer-backup.service && {
    echo "Upgrade stopped: pre-migration backup failed" >&2
    exit 1
}

/opt/key-writer/deploy/scripts/preflight.sh
/opt/key-writer/.venv/bin/pip install --requirement requirements-prod.txt
/opt/key-writer/.venv/bin/python -m alembic upgrade head
systemctl restart key-writer.service
curl --fail --silent --show-error http://127.0.0.1:8100/healthz
echo
echo "Upgrade completed; verify the UI and journal before removing the previous release."
