from datetime import datetime, time
from zoneinfo import ZoneInfo


APPLICATION_TIMEZONE = ZoneInfo("Europe/Moscow")


def excel_safe_value(value):
    """Return a value that openpyxl can safely write to an Excel cell."""

    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(APPLICATION_TIMEZONE).replace(tzinfo=None)
    if isinstance(value, time) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value
