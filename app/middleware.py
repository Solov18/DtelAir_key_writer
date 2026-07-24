from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from app.access_control import has_permission
from app.repositories.user_repository import get_user_by_id


PUBLIC_PATHS = (
    "/login",
    "/static",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        if path.startswith(PUBLIC_PATHS):
            return await call_next(request)

        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse("/login", status_code=303)

        user = get_user_by_id(int(user_id))
        if not user or not int(user.get("active", 1)):
            request.session.clear()
            return RedirectResponse("/login", status_code=303)

        request.session["user"] = {
            "id": user["id"],
            "full_name": user["full_name"],
            "login": user["login"],
            "role": user["role"],
            "active": user["active"],
        }

        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            safe_posts = {
                "/search",
                "/message/preview",
                "/write/manual/preview",
                "/settings/training-mode",
            }
            simulated_posts = {
                "/message/write",
                "/write/manual/write",
            }
            training_mode = bool(request.session.get("training_mode"))

            if training_mode and path not in safe_posts | simulated_posts:
                return RedirectResponse(
                    "/?notice=training_blocked",
                    status_code=303,
                )

            if (
                not has_permission(user, "manage_registry")
                and path not in safe_posts
                and not (training_mode and path in simulated_posts)
            ):
                return RedirectResponse(
                    "/?notice=read_only",
                    status_code=303,
                )

        return await call_next(request)
