import json
import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from threading import RLock
from time import monotonic
from urllib.parse import urlsplit

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
    checked_at = datetime.now(timezone.utc).isoformat()
    if not crm_auth_configured():
        return {
            "ok": False,
            "status": "not_configured",
            "message": "CRM не настроена: задайте Cookie или логин, пароль и Buyer ID.",
            "http_status": None,
            "response_time_ms": None,
            "checked_at": checked_at,
        }
    started = monotonic()
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
                "status": "ok",
                "message": f"CRM доступна, сервер ответил HTTP {response.status_code}.",
                "http_status": response.status_code,
                "response_time_ms": max(1, round((monotonic() - started) * 1000)),
                "checked_at": checked_at,
            }
    except requests.Timeout:
        return {
            "ok": False,
            "status": "timeout",
            "message": "CRM не ответила за отведённое время.",
            "http_status": None,
            "response_time_ms": max(1, round((monotonic() - started) * 1000)),
            "checked_at": checked_at,
        }
    except requests.ConnectionError:
        return {
            "ok": False,
            "status": "connection_error",
            "message": "Не удалось установить соединение с CRM. Проверьте DNS и сетевой доступ.",
            "http_status": None,
            "response_time_ms": max(1, round((monotonic() - started) * 1000)),
            "checked_at": checked_at,
        }
    except CrmAuthError:
        return {
            "ok": False,
            "status": "auth_error",
            "message": "CRM отклонила текущие данные авторизации.",
            "http_status": None,
            "response_time_ms": max(1, round((monotonic() - started) * 1000)),
            "checked_at": checked_at,
        }
    except requests.RequestException:
        return {
            "ok": False,
            "status": "connection_error",
            "message": "Не удалось безопасно проверить подключение к CRM.",
            "http_status": None,
            "response_time_ms": max(1, round((monotonic() - started) * 1000)),
            "checked_at": checked_at,
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


CRM_CREATE_KEY_HEX_LENGTH = 8
CRM_DEVICE_KEY_VALUE_LENGTH = 14


def normalize_crm_key_hex(hex_value: str, *, operation: str) -> str:
    """Return the key representation required by a crm.dtel.ru endpoint.

    The create-key form sends the scanned 32-bit key code (eight hexadecimal
    characters) together with ``numberSystem=16``.  Device-key records returned
    by CRM expose a different, fixed-width ``VALUE`` field: the frontend passes
    that 14-character value verbatim to the DELETE URL.  Locally we keep the
    scanned value and expand it only at the integration boundary.
    """

    clean_hex = (hex_value or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]+", clean_hex):
        raise ValueError(f"Некорректный HEX ключа: {hex_value}")
    if operation == "create":
        if len(clean_hex) != CRM_CREATE_KEY_HEX_LENGTH:
            raise ValueError(f"Некорректный HEX ключа: {hex_value}")
        return clean_hex
    if operation == "delete":
        if len(clean_hex) > CRM_DEVICE_KEY_VALUE_LENGTH:
            raise ValueError(f"Некорректный HEX ключа: {hex_value}")
        return clean_hex.zfill(CRM_DEVICE_KEY_VALUE_LENGTH)
    raise ValueError(f"Неизвестная CRM-операция с ключом: {operation}")


def _validate_write_data(mac: str, hex_value: str) -> str | None:
    if not re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", mac.upper()):
        return f"Некорректный MAC-адрес панели: {mac}"

    if not re.fullmatch(
        rf"[0-9A-F]{{{CRM_CREATE_KEY_HEX_LENGTH}}}", hex_value.upper()
    ):
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
    *,
    timeout: float | None = None,
) -> requests.Response:
    """Delete a regular key using the contract used by crm.dtel.ru frontend.

    The central CRM endpoint owns communication with the physical device.  A
    regular-key delete has MAC and HEX in the URL and intentionally has no JSON
    body (flatNum/inner are create-key fields, not delete fields).
    """
    return session.delete(
        url,
        timeout=(
            max(0.1, float(timeout))
            if timeout is not None
            else max(1, float(settings.request_timeout))
        ),
        allow_redirects=False,
    )


def _classify_operation_response(data: dict, *, operation: str) -> dict:
    """Convert the real CRM response into stable, idempotent semantics."""

    ok = data.get("result") is True
    message = _message_text(data.get("message"))
    normalized = message.casefold().replace("ё", "е")
    if operation == "add":
        idempotent = not ok and any(
            marker in normalized
            for marker in ("уже существует", "уже добавлен", "already exists")
        )
        status = "SUCCESS" if ok else "ALREADY_EXISTS" if idempotent else "CRM_ERROR"
        fallback = "Ключ успешно записан" if ok else "CRM отклонила запись ключа"
        return _result(
            ok=ok or idempotent,
            written=ok,
            status=status,
            response=message or fallback,
        )

    not_confirmed = not ok and any(
        marker in normalized
        for marker in ("не найден", "не существует", "already absent", "not found")
    )
    status = "SUCCESS" if ok else "DELETE_NOT_CONFIRMED" if not_confirmed else "CRM_ERROR"
    return _result(
        ok=ok,
        status=status,
        response=message or ("Ключ успешно удалён" if ok else "CRM не подтвердила удаление ключа"),
    )


def _classify_delete_http_error(response: requests.Response) -> dict | None:
    """Accept only an explicit key-absence response as idempotent.

    A generic HTML ``404 Not Found`` means that the route itself is wrong.  It
    must never be converted into a successful deletion, otherwise local state
    can be freed while the key is still present in the central CRM.
    """
    if response.status_code != 404:
        return None
    message = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            message = _message_text(data.get("message") or data.get("error"))
    except (TypeError, ValueError):
        message = re.sub(r"<[^>]+>", " ", response.text or "")
    normalized = " ".join(message.casefold().replace("ё", "е").split())
    explicitly_absent = any(
        marker in normalized
        for marker in (
            "ключ не найден",
            "ключ не существует",
            "key not found",
            "key does not exist",
            "key already absent",
        )
    )
    if not explicitly_absent:
        return _result(
            ok=False,
            status="INVALID_ROUTE",
            response=(
                "Удаление в crm.dtel.ru не выполнено: HTTP 404, "
                "неверный маршрут"
            ),
        )
    return _result(
        ok=True,
        status="ALREADY_ABSENT",
        response="Ключ уже отсутствует в прежнем месте CRM",
    )


def _safe_response_fragment(response: requests.Response) -> str:
    """Small diagnostic fragment without headers, cookies or credentials."""
    try:
        data = response.json()
        value = _message_text(data.get("message") or data.get("error")) if isinstance(data, dict) else ""
    except (TypeError, ValueError):
        value = re.sub(r"<[^>]+>", " ", response.text or "")
    value = " ".join(value.split())
    return value[:240]


def _log_key_response(*, action: str, url: str, response: requests.Response) -> None:
    logger.info(
        "crm.key.response action=%s path=%s http_status=%s fragment=%s",
        action,
        urlsplit(url).path,
        response.status_code,
        _safe_response_fragment(response),
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

    external_hex = (
        normalize_crm_key_hex(clean_hex, operation="create")
        if operation == "add"
        else normalize_crm_key_hex(clean_hex, operation="delete")
    )
    if operation == "add":
        payload["value"] = external_hex
    url = (
        f"{_base_url()}/front/device-keys/{clean_mac}/create-key"
        if operation == "add"
        else f"{_base_url()}/front/device/{clean_mac}/key/{external_hex}/delete"
    )
    sender = _send_create_key if operation == "add" else _send_delete_key
    session = _new_session()
    session.headers.pop("Cookie", None)
    try:
        _login_explicit(session, login=login, password=password)
        logger.info(
            "crm.key.request action=%s method=%s path=%s mac=%s flat_num=%s inner=%s",
            operation, "POST" if operation == "add" else "DELETE",
            urlsplit(url).path, clean_mac, payload["flatNum"], payload["inner"],
        )
        if operation == "add":
            response = sender(
                session, url, payload,
                timeout=max(1, float(settings.request_timeout)),
            )
        else:
            response = sender(
                session, url,
                timeout=max(1, float(settings.request_timeout)),
            )
        _log_key_response(action=operation, url=url, response=response)
        if _is_auth_response(response):
            return _result(
                ok=False,
                status="AUTH_REQUIRED",
                response="Авторизация CRM для управляющей компании истекла",
            )
        if not response.ok:
            if operation == "remove":
                idempotent = _classify_delete_http_error(response)
                if idempotent:
                    return idempotent
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
        return _classify_operation_response(data, operation=operation)
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

    payload["value"] = normalize_crm_key_hex(clean_hex, operation="create")

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

            classified = _classify_operation_response(data, operation="add")
            logger.info(
                "key_write.crm.response mac=%s status=%s",
                clean_mac,
                classified["status"],
            )
            return classified

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


def crm_remove_key(mac: str, hex_value: str, flat_num: str, inner: int) -> dict:
    """Remove a key through the same authenticated CRM API as create-key."""

    clean_mac = (mac or "").strip().upper()
    clean_hex = (hex_value or "").strip().upper()
    validation_error = _validate_write_data(clean_mac, clean_hex)
    if validation_error:
        return _result(ok=False, status="VALIDATION_ERROR", response=validation_error)
    if settings.dry_run:
        return _result(
            ok=True,
            status="DRY_RUN",
            response="Тестовый режим: запрос удаления в CRM не отправлен",
        )

    operation_timeout = max(1, float(settings.request_timeout))
    deadline = monotonic() + operation_timeout
    external_hex = normalize_crm_key_hex(clean_hex, operation="delete")
    url = f"{_base_url()}/front/device/{clean_mac}/key/{external_hex}/delete"
    logger.info("key_delete.crm.start mac=%s timeout_seconds=%s", clean_mac, operation_timeout)
    if not _crm_lock.acquire(timeout=operation_timeout):
        return _result(ok=False, status="TIMEOUT", response="Превышено время ожидания очереди удаления в CRM")
    try:
        try:
            session = _get_session(deadline=deadline)
            logger.info(
                "crm.key.request action=remove method=DELETE path=%s mac=%s",
                urlsplit(url).path, clean_mac,
            )
            response = _send_delete_key(
                session, url, timeout=_remaining_timeout(deadline)
            )
            _log_key_response(action="remove", url=url, response=response)
            if _is_auth_response(response) and _has_login_credentials():
                _reset_session()
                session = _get_session(deadline=deadline)
                response = _send_delete_key(
                    session, url, timeout=_remaining_timeout(deadline)
                )
                _log_key_response(action="remove", url=url, response=response)
            if _is_auth_response(response):
                return _result(ok=False, status="AUTH_REQUIRED", response="Авторизация CRM истекла")
            if not response.ok:
                idempotent = _classify_delete_http_error(response)
                if idempotent:
                    return idempotent
                return _result(ok=False, status=f"HTTP_{response.status_code}", response=_response_text(response))
            try:
                data = response.json()
            except ValueError:
                return _result(ok=False, status="INVALID_RESPONSE", response=_response_text(response))
            return _classify_operation_response(data, operation="remove")
        except CrmAuthError as error:
            return _result(ok=False, status="AUTH_REQUIRED", response=str(error))
        except requests.Timeout:
            return _result(ok=False, status="TIMEOUT", response="CRM не ответила за отведённое время")
        except requests.RequestException:
            return _result(ok=False, status="CONNECTION_ERROR", response="CRM или панель недоступны")
        except Exception:
            logger.exception("key_delete.crm.unexpected_error mac=%s", clean_mac)
            return _result(ok=False, status="ERROR", response="Непредвиденная ошибка удаления ключа")
    finally:
        _crm_lock.release()
        logger.info("key_delete.crm.finish mac=%s", clean_mac)
