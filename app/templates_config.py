from pathlib import Path
from datetime import date, datetime
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.presentation import operation_status_name, operation_status_tone
from app.access_control import has_permission, is_lookup_user, role_label

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


def csrf_token(request: Request) -> str:
    return str(request.session.get("csrf_token") or "")


def format_datetime(value, *, with_seconds: bool = False) -> str:
    if value in (None, ""):
        return "—"
    if isinstance(value, str):
        raw_value = value.strip()
        try:
            value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(raw_value)
            except ValueError:
                return raw_value
            return parsed_date.strftime("%d.%m.%Y")
    if isinstance(value, datetime):
        pattern = "%d.%m.%Y %H:%M:%S" if with_seconds else "%d.%m.%Y %H:%M"
        return value.strftime(pattern)
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value)


def format_datetime_seconds(value) -> str:
    return format_datetime(value, with_seconds=True)


templates.env.globals["current_user"] = current_user
templates.env.globals["operation_status_name"] = operation_status_name
templates.env.globals["operation_status_tone"] = operation_status_tone
templates.env.globals["role_label"] = role_label
templates.env.globals["has_permission"] = has_permission
templates.env.globals["is_lookup_user"] = is_lookup_user
templates.env.globals["training_mode"] = (
    lambda request: bool(request.session.get("training_mode"))
)
templates.env.globals["notice_code"] = notice_code
templates.env.globals["csrf_token"] = csrf_token
templates.env.globals["format_datetime"] = format_datetime
templates.env.globals["format_datetime_seconds"] = format_datetime_seconds
templates.env.filters["datetime"] = format_datetime
templates.env.filters["datetime_seconds"] = format_datetime_seconds
