import json
import re
from html.parser import HTMLParser
from threading import RLock

import requests

from app.settings import settings


class CrmAuthError(RuntimeError):
    pass


class _CsrfParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        values = dict(attrs)

        if tag == "meta" and values.get("name") == "csrf-token":
            self.token = values.get("content", "")
        elif tag == "input" and values.get("name") == "_csrf":
            self.token = values.get("value", "")


_crm_lock = RLock()
_crm_session: requests.Session | None = None
_crm_session_authenticated = False


def _base_url() -> str:
    return settings.crm_base_url.rstrip("/")


def _normalize_cookie(value: str) -> str:
    cookie = (value or "").strip()

    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()

    return cookie


def _has_login_credentials() -> bool:
    return bool(
        settings.crm_login.strip()
        and settings.crm_password
        and settings.crm_buyer_id.strip()
    )


def crm_auth_configured() -> bool:
    return bool(_normalize_cookie(settings.crm_cookie) or _has_login_credentials())


def _extract_csrf(html: str) -> str:
    parser = _CsrfParser()
    parser.feed(html or "")
    return parser.token.strip()


def _response_text(response: requests.Response) -> str:
    text = (response.text or "").strip()
    return text[:1000] or "CRM вернула пустой ответ"


def _message_text(value) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return json.dumps(value, ensure_ascii=False)[:1000]


def _is_auth_response(response: requests.Response) -> bool:
    if response.status_code in (401, 403):
        return True

    if 300 <= response.status_code < 400:
        return "site/auth" in response.headers.get("Location", "")

    content_type = response.headers.get("Content-Type", "").lower()
    text = (response.text or "").lower()

    return (
        "text/html" in content_type
        and (
            "site-login" in text
            or "пожалуйста, введите данные для входа" in text
        )
    )


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": _base_url(),
            "Referer": f"{_base_url()}/",
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    cookie = _normalize_cookie(settings.crm_cookie)

    if cookie:
        session.headers["Cookie"] = cookie

    return session


def _reset_session() -> None:
    global _crm_session
    global _crm_session_authenticated

    if _crm_session is not None:
        _crm_session.close()

    _crm_session = None
    _crm_session_authenticated = False


def _login(session: requests.Session) -> None:
    global _crm_session_authenticated

    login_page = session.get(
        f"{_base_url()}/site/auth",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": None,
            "Origin": None,
            "X-Requested-With": None,
        },
        timeout=settings.request_timeout,
    )

    if login_page.status_code != 200:
        raise CrmAuthError(
            f"CRM не открыла страницу входа: HTTP {login_page.status_code}"
        )

    csrf_token = _extract_csrf(login_page.text)

    if not csrf_token:
        raise CrmAuthError("CRM не вернула CSRF-токен для входа")

    response = session.post(
        f"{_base_url()}/site/auth/login",
        json={
            "buyer": settings.crm_buyer_id.strip(),
            "username": settings.crm_login.strip(),
            "password": settings.crm_password,
            "rememberMe": True,
        },
        headers={"X-CSRF-Token": csrf_token},
        timeout=settings.request_timeout,
        allow_redirects=False,
    )

    try:
        data = response.json()
    except ValueError as error:
        raise CrmAuthError(
            f"CRM вернула некорректный ответ при входе: {_response_text(response)}"
        ) from error

    if not response.ok or data.get("result") is not True:
        message = _message_text(data.get("message"))
        raise CrmAuthError(message or "CRM отклонила логин, пароль или ID компании")

    session.headers["X-CSRF-Token"] = csrf_token
    _crm_session_authenticated = True


def _get_session() -> requests.Session:
    global _crm_session

    if _crm_session is None:
        _crm_session = _new_session()

    if _normalize_cookie(settings.crm_cookie):
        return _crm_session

    if not _has_login_credentials():
        raise CrmAuthError(
            "Укажите CRM_COOKIE или CRM_LOGIN, CRM_PASSWORD и CRM_BUYER_ID в .env"
        )

    if not _crm_session_authenticated:
        _login(_crm_session)

    return _crm_session


def _validate_write_data(mac: str, hex_value: str) -> str | None:
    if not re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", mac.upper()):
        return f"Некорректный MAC-адрес панели: {mac}"

    if not re.fullmatch(r"[0-9A-F]{8}", hex_value.upper()):
        return f"Некорректный HEX ключа: {hex_value}"

    return None


def _result(
    *,
    ok: bool,
    status: str,
    response: str,
    written: bool = False,
) -> dict:
    return {
        "ok": ok,
        "written": written,
        "status": status,
        "response": response,
        "message": response,
    }


def _send_create_key(
    session: requests.Session,
    url: str,
    payload: dict,
) -> requests.Response:
    return session.post(
        url,
        json=payload,
        timeout=settings.request_timeout,
        allow_redirects=False,
    )


def crm_add_key(
    mac: str,
    hex_value: str,
    flat_num: str,
    inner: int,
):
    clean_mac = (mac or "").strip().upper()
    clean_hex = (hex_value or "").strip().upper()
    url = f"{_base_url()}/front/device-keys/{clean_mac}/create-key"

    payload = {
        "value": clean_hex,
        "numberSystem": "16",
        "flatNum": str(flat_num or "0"),
        "inner": int(inner),
    }

    validation_error = _validate_write_data(clean_mac, clean_hex)

    if validation_error:
        return _result(
            ok=False,
            status="VALIDATION_ERROR",
            response=validation_error,
        )

    if settings.dry_run:
        return _result(
            ok=True,
            status="DRY_RUN",
            response=(
                "Тестовый режим: запрос не отправлен в CRM. "
                + json.dumps(payload, ensure_ascii=False)
            ),
        )

    with _crm_lock:
        try:
            session = _get_session()
            response = _send_create_key(session, url, payload)

            if _is_auth_response(response) and _has_login_credentials():
                _reset_session()
                session = _get_session()
                response = _send_create_key(session, url, payload)

            if _is_auth_response(response):
                return _result(
                    ok=False,
                    status="AUTH_REQUIRED",
                    response=(
                        "Авторизация CRM истекла. Обновите CRM_COOKIE "
                        "или проверьте CRM_LOGIN, CRM_PASSWORD и CRM_BUYER_ID."
                    ),
                )

            if not response.ok:
                return _result(
                    ok=False,
                    status=f"HTTP_{response.status_code}",
                    response=_response_text(response),
                )

            try:
                data = response.json()
            except ValueError:
                return _result(
                    ok=False,
                    status="INVALID_RESPONSE",
                    response=_response_text(response),
                )

            message = _message_text(data.get("message"))
            ok = data.get("result") is True

            return _result(
                ok=ok,
                written=ok,
                status="SUCCESS" if ok else "CRM_ERROR",
                response=message or (
                    "Ключ успешно записан"
                    if ok
                    else "CRM отклонила запись ключа"
                ),
            )

        except CrmAuthError as error:
            return _result(
                ok=False,
                status="AUTH_REQUIRED",
                response=str(error),
            )
        except requests.Timeout:
            return _result(
                ok=False,
                status="TIMEOUT",
                response="CRM не ответила за отведённое время",
            )
        except requests.RequestException as error:
            return _result(
                ok=False,
                status="CONNECTION_ERROR",
                response=f"Ошибка соединения с CRM: {error}",
            )
        except Exception as error:
            return _result(
                ok=False,
                status="ERROR",
                response=str(error),
            )
