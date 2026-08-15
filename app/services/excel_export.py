from datetime import datetime, time
from zoneinfo import ZoneInfo

from openpyxl.cell import WriteOnlyCell


APPLICATION_TIMEZONE = ZoneInfo("Europe/Moscow")


def excel_safe_value(value):
    """Return a value that openpyxl can safely write to an Excel cell."""

    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(APPLICATION_TIMEZONE).replace(tzinfo=None)
    if isinstance(value, time) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def excel_text_cell(worksheet, value) -> WriteOnlyCell:
    """Create a text cell so Excel preserves accounting identifiers verbatim."""

    cell = WriteOnlyCell(worksheet, value=str(value or ""))
    cell.number_format = "@"
    return cell
