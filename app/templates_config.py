from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.presentation import operation_status_name, operation_status_tone

BASE = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=str(BASE / "templates")
)


def current_user(request: Request):
    return request.session.get("user")


templates.env.globals["current_user"] = current_user
templates.env.globals["operation_status_name"] = operation_status_name
templates.env.globals["operation_status_tone"] = operation_status_tone
