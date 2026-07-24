from pathlib import Path
from app.middleware import AuthMiddleware
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.db import init_db
from app.settings import settings
from app.routers import (
    auth,
    home,
    panels,
    employees,
    search,
    message,
    manual_write,
    uk,
    keys,
    log,
    users,
    settings as settings_router,
)

app = FastAPI(title="Dtel Access Manager")

app.add_middleware(AuthMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.session_https_only,
)


BASE = Path(__file__).resolve().parent

app.mount(
    "/static",
    StaticFiles(directory=str(BASE / "static")),
    name="static",
)


@app.on_event("startup")
def startup():
    init_db()

app.include_router(auth.router)
app.include_router(home.router)
app.include_router(panels.router)
app.include_router(employees.router)
app.include_router(search.router)
app.include_router(message.router)
app.include_router(manual_write.router)
app.include_router(uk.router)
app.include_router(keys.router)
app.include_router(log.router)
app.include_router(users.router)
app.include_router(settings_router.router)

for route in app.routes:
    print("ROUTE:", route.path)
