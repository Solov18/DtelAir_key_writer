"""Presentation helpers for the main dashboard."""

from __future__ import annotations

import calendar as calendar_module
from datetime import datetime
from zoneinfo import ZoneInfo


MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")
RUSSIAN_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
RUSSIAN_MONTHS_NOMINATIVE = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


def _local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=MOSCOW_TIMEZONE)
    return value.astimezone(MOSCOW_TIMEZONE)


def format_monitor_sync(value: datetime | None, *, now: datetime | None = None) -> str:
    local_value = _local_datetime(value)
    if local_value is None:
        return "Не выполнялась"

    local_now = _local_datetime(now) if now else datetime.now(MOSCOW_TIMEZONE)
    if local_value.date() == local_now.date():
        prefix = "Сегодня"
    elif (local_now.date() - local_value.date()).days == 1:
        prefix = "Вчера"
    else:
        return local_value.strftime("%d.%m.%Y, %H:%M")
    return f"{prefix}, {local_value:%H:%M}"


def monitor_status_view(snapshot: dict) -> dict:
    if snapshot.get("monitor_finished_at") is None:
        return {"label": "Нет данных", "tone": "info"}
    if snapshot.get("monitor_status") == "failed":
        return {"label": "Ошибка", "tone": "error"}
    if int(snapshot.get("monitor_failed") or 0):
        return {"label": "С предупреждениями", "tone": "warning"}
    return {"label": "Успешно", "tone": "success"}


def build_calendar(*, now: datetime | None = None) -> dict:
    local_now = _local_datetime(now) if now else datetime.now(MOSCOW_TIMEZONE)
    month = calendar_module.Calendar(firstweekday=calendar_module.MONDAY)
    weeks = []
    for week in month.monthdayscalendar(local_now.year, local_now.month):
        weeks.append(
            [
                {
                    "day": day,
                    "today": day == local_now.day,
                }
                for day in week
            ]
        )
    return {
        "month_name": RUSSIAN_MONTHS_NOMINATIVE[local_now.month],
        "year": local_now.year,
        "today_label": (
            f"Сегодня: {local_now.day} "
            f"{RUSSIAN_MONTHS[local_now.month]} {local_now.year}"
        ),
        "weeks": weeks,
    }
