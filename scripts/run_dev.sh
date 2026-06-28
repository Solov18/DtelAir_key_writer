#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
