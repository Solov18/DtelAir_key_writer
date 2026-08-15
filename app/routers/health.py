"""Minimal readiness endpoint for systemd and the reverse proxy."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import get_engine


router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthcheck():
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
