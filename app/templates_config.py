from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.presentation import operation_status_name, operation_status_tone
from app.access_control import has_permission, role_label

BASE = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=str(BASE / "templates")
)


def current_user(request: Request):
    return request.session.get("user")


def notice_code(request: Request) -> str:
    raw_query = request.scope.get("query_string", b"")
    if isinstance(raw_query, bytes):
        raw_query = raw_query.decode("utf-8", errors="ignore")
    return parse_qs(str(raw_query)).get("notice", [""])[0]


templates.env.globals["current_user"] = current_user
templates.env.globals["operation_status_name"] = operation_status_name
templates.env.globals["operation_status_tone"] = operation_status_tone
templates.env.globals["role_label"] = role_label
templates.env.globals["has_permission"] = has_permission
templates.env.globals["training_mode"] = (
    lambda request: bool(request.session.get("training_mode"))
)
templates.env.globals["notice_code"] = notice_code
