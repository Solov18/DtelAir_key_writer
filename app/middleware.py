from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse


PUBLIC_PATHS = (
    "/login",
    "/static",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        if path.startswith(PUBLIC_PATHS):
            return await call_next(request)

        if not request.session.get("user_id"):
            return RedirectResponse("/login", status_code=303)

        return await call_next(request)