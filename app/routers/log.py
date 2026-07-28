from datetime import date, timedelta
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.repositories.log_repository import (
    OBJECT_TYPE_NAMES,
    count_operations,
    get_operation_actions,
    get_operations,
)
from app.repositories.user_repository import get_users
from app.templates_config import templates

router = APIRouter()

_PERIODS = {"today", "yesterday", "7d", "30d", "all", "custom"}
_STATUSES = {"success", "warning", "error"}
_LIMITS = {25, 50, 100}


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _valid_iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return ""


def _period_dates(period: str, today: date) -> tuple[str, str]:
    if period == "today":
        current = today.isoformat()
        return current, current
    if period == "yesterday":
        previous = (today - timedelta(days=1)).isoformat()
        return previous, previous
    if period == "7d":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if period == "30d":
        return (today - timedelta(days=29)).isoformat(), today.isoformat()
    return "", ""


def _page_numbers(page: int, page_count: int) -> list[int]:
    if page_count <= 7:
        return list(range(1, page_count + 1))
    values = {1, page_count, page - 1, page, page + 1}
    return sorted(value for value in values if 1 <= value <= page_count)


@router.get("/log", response_class=HTMLResponse)
def log_page(request: Request):
    query = request.query_params
    period = query.get("period", "").strip().lower()
    date_from = _valid_iso_date(query.get("date_from", "").strip())
    date_to = _valid_iso_date(query.get("date_to", "").strip())

    if period not in _PERIODS:
        period = "custom" if date_from or date_to else "all"
    if period not in {"all", "custom"}:
        date_from, date_to = _period_dates(period, date.today())
    elif period == "all":
        date_from = date_to = ""

    selected_user_id = _positive_int(query.get("user_id"), 0) or None
    selected_action = query.get("action", "").strip()
    selected_object_type = query.get("object_type", "").strip().lower()
    if selected_object_type not in OBJECT_TYPE_NAMES:
        selected_object_type = ""
    selected_status = query.get("status", "").strip().lower()
    if selected_status not in _STATUSES:
        selected_status = ""
    search = query.get("search", query.get("q", "")).strip()
    sort_order = "asc" if query.get("sort_order", "").lower() == "asc" else "desc"
    limit = _positive_int(query.get("limit"), 50)
    if limit not in _LIMITS:
        limit = 50
    requested_page = _positive_int(query.get("page"), 1)

    repository_filters = {
        "date_from": date_from or None,
        "date_to": date_to or None,
        "user_id": selected_user_id,
        "action": selected_action or None,
        "object_type": selected_object_type or None,
        "status": selected_status or None,
        "search": search or None,
    }
    total = count_operations(**repository_filters)
    page_count = max(1, ceil(total / limit))
    page = min(requested_page, page_count)
    rows = get_operations(
        **repository_filters,
        limit=limit,
        offset=(page - 1) * limit,
        sort_order=sort_order,
    )

    preserved_query = {
        "period": period,
        "date_from": date_from,
        "date_to": date_to,
        "user_id": selected_user_id or "",
        "action": selected_action,
        "object_type": selected_object_type,
        "status": selected_status,
        "search": search,
        "sort_order": sort_order,
        "limit": limit,
    }

    def page_url(target: int) -> str:
        values = {**preserved_query, "page": target}
        return "/log?" + urlencode(
            {key: value for key, value in values.items() if value not in ("", None)}
        )

    return templates.TemplateResponse(
        "log.html",
        {
            "request": request,
            "rows": rows,
            "total": total,
            "users": get_users(),
            "actions": get_operation_actions(),
            "object_types": OBJECT_TYPE_NAMES,
            "filters": {
                **preserved_query,
                "user_id": selected_user_id,
            },
            "page": page,
            "page_count": page_count,
            "page_numbers": [
                {"number": number, "url": page_url(number)}
                for number in _page_numbers(page, page_count)
            ],
            "previous_url": page_url(page - 1) if page > 1 else "",
            "next_url": page_url(page + 1) if page < page_count else "",
            "range_from": (page - 1) * limit + 1 if total else 0,
            "range_to": min(page * limit, total),
        },
    )
