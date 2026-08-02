import json
import logging
import re
from html.parser import HTMLParser
from threading import RLock
from time import monotonic

import requests

from app.settings import settings


logger = logging.getLogger("uvicorn.error")


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


def check_crm_connection() -> dict:
    """Authenticate and perform one read-only request without exposing secrets."""
    if not crm_auth_configured():
        return {
            "ok": False,
            "message": "CRM не настроена: задайте Cookie или логин, пароль и Buyer ID.",
        }
    try:
        with _crm_lock:
            _reset_session()
            session = _get_session()
            response = session.get(
                f"{_base_url()}/",
                headers={"Content-Type": None},
                timeout=settings.request_timeout,
                allow_redirects=False,
            )
            if _is_auth_response(response):
                raise CrmAuthError("CRM отклонила текущие данные авторизации")
            if response.status_code >= 500:
                raise CrmAuthError(f"CRM временно недоступна: HTTP {response.status_code}")
            return {
                "ok": True,
                "message": f"CRM доступна, сервер ответил HTTP {response.status_code}.",
            }
    except (CrmAuthError, requests.RequestException) as error:
        return {
            "ok": False,
            "message": str(error)[:300] or "Не удалось проверить подключение к CRM.",
        }


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


def _remaining_timeout(deadline: float | None = None) -> float:
    """Return a bounded timeout and stop a multi-step CRM call at its deadline."""

    if deadline is None:
        return max(1, float(settings.request_timeout))
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise requests.Timeout("CRM request deadline exceeded")
    return max(0.1, remaining)


def _login(session: requests.Session, *, deadline: float | None = None) -> None:
    global _crm_session_authenticated

    login_page = session.get(
        f"{_base_url()}/site/auth",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": None,
            "Origin": None,
            "X-Requested-With": None,
        },
        timeout=_remaining_timeout(deadline),
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
        timeout=_remaining_timeout(deadline),
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


def _get_session(*, deadline: float | None = None) -> requests.Session:
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
        _login(_crm_session, deadline=deadline)

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
    *,
    timeout: float | None = None,
) -> requests.Response:
    return session.post(
        url,
        json=payload,
        timeout=(
            max(0.1, float(timeout))
            if timeout is not None
            else max(1, float(settings.request_timeout))
        ),
        allow_redirects=False,
    )


def _send_delete_key(
    session: requests.Session,
    url: str,
    payload: dict,
) -> requests.Response:
    return session.post(
        url,
        json=payload,
        timeout=max(1, float(settings.request_timeout)),
        allow_redirects=False,
    )


def _login_explicit(
    session: requests.Session,
    *,
    login: str,
    password: str,
) -> None:
    """Authenticate an isolated UK session without touching global settings."""

    if not login.strip() or not password or not settings.crm_buyer_id.strip():
        raise CrmAuthError("Для УК не настроены полные реквизиты CRM")

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
            "username": login.strip(),
            "password": password,
            "rememberMe": False,
        },
        headers={"X-CSRF-Token": csrf_token},
        timeout=settings.request_timeout,
        allow_redirects=False,
    )
    try:
        data = response.json()
    except ValueError as error:
        raise CrmAuthError("CRM вернула некорректный ответ при входе") from error
    if not response.ok or data.get("result") is not True:
        raise CrmAuthError("CRM отклонила реквизиты управляющей компании")
    session.headers["X-CSRF-Token"] = csrf_token


def _company_key_operation(
    *,
    operation: str,
    mac: str,
    hex_value: str,
    flat_num: str,
    inner: int,
    login: str,
    password: str,
) -> dict:
    clean_mac = (mac or "").strip().upper()
    clean_hex = (hex_value or "").strip().upper()
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
            response="Тестовый режим: запрос в CRM не отправлен",
        )

    endpoint = "create-key" if operation == "add" else "delete-key"
    url = f"{_base_url()}/front/device-keys/{clean_mac}/{endpoint}"
    sender = _send_create_key if operation == "add" else _send_delete_key
    session = _new_session()
    session.headers.pop("Cookie", None)
    try:
        _login_explicit(session, login=login, password=password)
        response = sender(session, url, payload)
        if _is_auth_response(response):
            return _result(
                ok=False,
                status="AUTH_REQUIRED",
                response="Авторизация CRM для управляющей компании истекла",
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
        ok = data.get("result") is True
        message = _message_text(data.get("message"))
        return _result(
            ok=ok,
            written=ok and operation == "add",
            status="SUCCESS" if ok else "CRM_ERROR",
            response=message or (
                "Ключ успешно записан"
                if ok and operation == "add"
                else "Ключ успешно удалён"
                if ok
                else "CRM отклонила операцию"
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
    except requests.RequestException:
        return _result(
            ok=False,
            status="CONNECTION_ERROR",
            response="Ошибка соединения с CRM",
        )
    except Exception:
        return _result(
            ok=False,
            status="ERROR",
            response="Непредвиденная ошибка CRM-операции",
        )
    finally:
        session.close()


def crm_add_key_for_company(
    mac: str,
    hex_value: str,
    flat_num: str,
    inner: int,
    *,
    login: str,
    password: str,
) -> dict:
    return _company_key_operation(
        operation="add",
        mac=mac,
        hex_value=hex_value,
        flat_num=flat_num,
        inner=inner,
        login=login,
        password=password,
    )


def crm_remove_key_for_company(
    mac: str,
    hex_value: str,
    flat_num: str,
    inner: int,
    *,
    login: str,
    password: str,
) -> dict:
    return _company_key_operation(
        operation="remove",
        mac=mac,
        hex_value=hex_value,
        flat_num=flat_num,
        inner=inner,
        login=login,
        password=password,
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

    operation_timeout = max(1, float(settings.request_timeout))
    deadline = monotonic() + operation_timeout
    logger.info(
        "key_write.crm.start mac=%s timeout_seconds=%s",
        clean_mac,
        operation_timeout,
    )
    if not _crm_lock.acquire(timeout=operation_timeout):
        logger.warning("key_write.crm.lock_timeout mac=%s", clean_mac)
        return _result(
            ok=False,
            status="TIMEOUT",
            response="Превышено время ожидания очереди записи в CRM",
        )

    try:
        try:
            logger.info("key_write.crm.session mac=%s", clean_mac)
            session = _get_session(deadline=deadline)
            logger.info("key_write.crm.request mac=%s", clean_mac)
            response = _send_create_key(
                session,
                url,
                payload,
                timeout=_remaining_timeout(deadline),
            )

            if _is_auth_response(response) and _has_login_credentials():
                logger.info("key_write.crm.reauth mac=%s", clean_mac)
                _reset_session()
                session = _get_session(deadline=deadline)
                response = _send_create_key(
                    session,
                    url,
                    payload,
                    timeout=_remaining_timeout(deadline),
                )

            if _is_auth_response(response):
                logger.warning("key_write.crm.auth_error mac=%s", clean_mac)
                return _result(
                    ok=False,
                    status="AUTH_REQUIRED",
                    response=(
                        "Авторизация CRM истекла. Обновите CRM_COOKIE "
                        "или проверьте CRM_LOGIN, CRM_PASSWORD и CRM_BUYER_ID."
                    ),
                )

            if not response.ok:
                logger.warning(
                    "key_write.crm.http_error mac=%s status_code=%s",
                    clean_mac,
                    response.status_code,
                )
                return _result(
                    ok=False,
                    status=f"HTTP_{response.status_code}",
                    response=_response_text(response),
                )

            try:
                data = response.json()
            except ValueError:
                logger.warning("key_write.crm.invalid_response mac=%s", clean_mac)
                return _result(
                    ok=False,
                    status="INVALID_RESPONSE",
                    response=_response_text(response),
                )

            message = _message_text(data.get("message"))
            ok = data.get("result") is True
            normalized_message = message.casefold().replace("ё", "е")
            already_exists = (
                not ok
                and (
                    "уже существует" in normalized_message
                    or "уже добавлен" in normalized_message
                    or "already exists" in normalized_message
                )
            )
            status = "SUCCESS" if ok else "ALREADY_EXISTS" if already_exists else "CRM_ERROR"
            logger.info(
                "key_write.crm.response mac=%s status=%s",
                clean_mac,
                status,
            )

            return _result(
                ok=ok,
                written=ok,
                status=status,
                response=message or (
                    "Ключ успешно записан"
                    if ok
                    else "CRM отклонила запись ключа"
                ),
            )

        except CrmAuthError as error:
            logger.warning("key_write.crm.auth_exception mac=%s", clean_mac)
            return _result(
                ok=False,
                status="AUTH_REQUIRED",
                response=str(error),
            )
        except requests.Timeout:
            logger.warning("key_write.crm.timeout mac=%s", clean_mac)
            return _result(
                ok=False,
                status="TIMEOUT",
                response="CRM не ответила за отведённое время",
            )
        except requests.RequestException:
            logger.warning("key_write.crm.connection_error mac=%s", clean_mac)
            return _result(
                ok=False,
                status="CONNECTION_ERROR",
                response="CRM или панель недоступны",
            )
        except Exception:
            logger.exception("key_write.crm.unexpected_error mac=%s", clean_mac)
            return _result(
                ok=False,
                status="ERROR",
                response="Непредвиденная ошибка записи ключа",
            )
    finally:
        _crm_lock.release()
        logger.info("key_write.crm.finish mac=%s", clean_mac)
