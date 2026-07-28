import re


_SECRET_VALUE = re.compile(
    r"(?i)\b(password|passwd|cookie|token|secret|authorization)\b"
    r"\s*[:=]\s*([^,;\r\n]+)"
)


def redact_audit_text(value: object) -> str:
    """Return audit text with credentials removed, including legacy rows."""
    return _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[СКРЫТО]", str(value or ""))
