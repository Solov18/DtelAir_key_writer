from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=str(BASE / "templates")
)


def current_user(request: Request):
    return request.session.get("user")


templates.env.globals["current_user"] = current_user