#!/bin/bash
set -Eeuo pipefail

cd /opt/key-writer
/opt/key-writer/.venv/bin/python scripts/production_preflight.py \
    --expect-database key_writer
/opt/key-writer/.venv/bin/python -m alembic current
/opt/key-writer/.venv/bin/python -m alembic heads
