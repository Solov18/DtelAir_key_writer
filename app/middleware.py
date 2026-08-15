from __future__ import annotations

import hmac
import secrets
from urllib.parse import parse_qs

from fastapi.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app.access_control import has_permission, is_lookup_user
from app.repositories.user_repository import get_user_by_id


PUBLIC_PATHS = ("/login", "/static", "/healthz")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOOKUP_ALLOWED_METHODS = {
    "/search": {"GET", "HEAD", "POST"},
    "/api/search/suggestions": {"GET", "HEAD"},
    "/logout": {"POST"},
}


def _required_permission(path: str, method: str) -> str:
    unsafe = method not in SAFE_METHODS
    if path == "/search" or path == "/api/search/suggestions":
        return "use_universal_search"
    if path.startswith("/settings"):
        return "manage_settings"
    if path.startswith("/users"):
        return "manage_users"
    if path.startswith("/log"):
        return "view_logs"
    if path.startswith("/panels"):
        return "manage_panels" if unsafe else "view"
    if path.startswith("/employees"):
        return "manage_employees" if unsafe else "view"
    if path.startswith("/uk"):
        return "manage_uk" if unsafe else "view"
    if path.startswith("/keys"):
        return "manage_keys" if unsafe else "view"
    if path.startswith("/message/write") or path.startswith("/write/manual/write"):
        return "write_keys"
    return "view"


def _csrf_token(request) -> str:
    token = str(request.session.get("csrf_token") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        expected_csrf = _csrf_token(request)

        if request.method not in SAFE_METHODS:
            supplied_csrf = request.headers.get("X-CSRF-Token", "")
            if not supplied_csrf:
                try:
                    body = await request.body()
                    content_type = request.headers.get("content-type", "")
                    if content_type.startswith("application/x-www-form-urlencoded"):
                        supplied_csrf = parse_qs(
                            body.decode("utf-8", errors="ignore")
                        ).get("csrf_token", [""])[0]
                    elif content_type.startswith("multipart/form-data"):
                        marker = b'name="csrf_token"'
                        marker_at = body.find(marker)
                        if marker_at >= 0:
                            value_at = body.find(b"\r\n\r\n", marker_at)
                            value_end = body.find(b"\r\n", value_at + 4)
                            if value_at >= 0 and value_end >= 0:
                                supplied_csrf = body[value_at + 4:value_end].decode(
                                    "utf-8", errors="ignore"
                                )
                except Exception:
                    supplied_csrf = ""
            if not supplied_csrf or not hmac.compare_digest(
                supplied_csrf,
                expected_csrf,
            ):
                return PlainTextResponse(
                    "CSRF-проверка не пройдена. Обновите страницу и повторите действие.",
                    status_code=403,
                )

        if path.startswith(PUBLIC_PATHS):
            return await call_next(request)

        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse("/login", status_code=303)

        # Repositories use synchronous SQLAlchemy sessions.  Middleware runs
        # in the async request path, so the user lookup must not block the
        # Uvicorn event loop on every authenticated request.
        user = await run_in_threadpool(get_user_by_id, int(user_id))
        if not user or not int(user.get("active", 1)):
            request.session.clear()
            return RedirectResponse("/login", status_code=303)

        request.session["user"] = {
            "id": user["id"],
            "full_name": user["full_name"],
            "login": user["login"],
            "role": user["role"],
            "role_id": user["role_id"],
            "role_name": user["role_name"],
            "permissions": sorted(user["permissions"]),
            "active": user["active"],
        }

        if is_lookup_user(user):
            if path == "/" and request.method in {"GET", "HEAD"}:
                return RedirectResponse("/search", status_code=303)
            allowed_methods = LOOKUP_ALLOWED_METHODS.get(path, set())
            if request.method not in allowed_methods:
                if path.startswith("/api/"):
                    return JSONResponse(
                        {"detail": "Недостаточно прав"},
                        status_code=403,
                    )
                return RedirectResponse(
                    "/search?notice=read_only",
                    status_code=303,
                )
            if path == "/logout":
                return await call_next(request)

        permission = _required_permission(path, request.method)
        if not has_permission(user, permission):
            return RedirectResponse("/?notice=read_only", status_code=303)

        if request.method not in SAFE_METHODS:
            training_mode = bool(request.session.get("training_mode"))
            simulated_posts = {"/message/write", "/write/manual/write"}
            safe_training_posts = {
                "/search",
                "/message/preview",
                "/write/manual/preview",
                "/settings/training-mode",
            }
            if (
                training_mode
                and path not in simulated_posts
                and path not in safe_training_posts
            ):
                return RedirectResponse(
                    "/?notice=training_blocked",
                    status_code=303,
                )

        return await call_next(request)
