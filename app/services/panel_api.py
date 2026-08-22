import time
import logging
from datetime import datetime, timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from app.settings import settings


logger = logging.getLogger(__name__)
TRANSIENT_CHECK_ATTEMPTS = 2
TRANSIENT_RETRY_DELAY_SECONDS = 0.15


class PanelApiError(RuntimeError):
    def __init__(self, message: str, status: str = "error"):
        super().__init__(message)
        self.status = status


def panel_api_configured() -> bool:
    return bool(
        settings.panel_api_login.strip()
        and settings.panel_api_password
    )


def _base_url(panel: dict) -> str:
    host = str(panel.get("ip") or "").strip().strip("/")
    if not host:
        raise PanelApiError("У панели не указан IP-адрес", "no_ip")
    return f"http://{host}"


def _http_request(
    method: str,
    url: str,
    *,
    session: requests.Session | None = None,
    **kwargs,
) -> requests.Response:
    """Send panel requests directly, without workstation proxy settings."""
    owned_session = session is None
    session = session or requests.Session()
    session.trust_env = False
    try:
        return session.request(method, url, **kwargs)
    finally:
        if owned_session:
            session.close()


def _request(
    panel: dict,
    method: str,
    path: str,
    *,
    expect_json: bool = True,
    session: requests.Session | None = None,
) -> tuple[requests.Response, Any, int]:
    if not panel_api_configured():
        raise PanelApiError(
            "Общие логин и пароль API не настроены",
            "not_configured",
        )

    started = time.perf_counter()
    try:
        response = _http_request(
            method,
            f"{_base_url(panel)}{path}",
            session=session,
            auth=HTTPBasicAuth(
                settings.panel_api_login.strip(),
                settings.panel_api_password,
            ),
            headers={"Accept": "application/json"},
            timeout=max(0.5, float(settings.panel_api_timeout)),
        )
    except requests.Timeout as error:
        raise PanelApiError("Панель не ответила за отведённое время", "timeout") from error
    except requests.ConnectionError as error:
        raise PanelApiError("Нет соединения с панелью", "offline") from error
    except requests.RequestException as error:
        raise PanelApiError("Сетевая ошибка при обращении к панели", "other_error") from error

    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    if response.status_code == 401:
        raise PanelApiError("Панель отклонила логин или пароль", "other_error")
    if response.status_code >= 400:
        raise PanelApiError(
            f"API панели вернул HTTP {response.status_code}",
            "other_error",
        )

    if not expect_json:
        return response, response.content, elapsed_ms

    try:
        payload = response.json() if response.content else {}
    except ValueError as error:
        raise PanelApiError("Панель вернула некорректный ответ", "other_error") from error
    return response, payload, elapsed_ms


def _firmware_name(payload: dict) -> str:
    for section in ("opt", "rootfs", "media"):
        value = payload.get(section)
        if isinstance(value, dict) and value.get("name"):
            return str(value["name"])
    return ""


def _check_panel_once(panel: dict) -> dict:
    started = time.perf_counter()
    session = requests.Session()
    session.trust_env = False
    try:
        _, info, _ = _request(panel, "GET", "/system/info", session=session)
        supply_voltage = None
        try:
            _, mcu_info, _ = _request(panel, "GET", "/v1/mcu/info", session=session)
            if isinstance(mcu_info, dict):
                power = mcu_info.get("power")
                if isinstance(power, dict):
                    supply_voltage = power.get("dc")
        except PanelApiError as error:
            if error.status in {"timeout", "offline", "other_error", "not_configured"}:
                raise

        firmware = ""
        try:
            _, versions, _ = _request(panel, "GET", "/v2/system/versions", session=session)
            firmware = _firmware_name(versions if isinstance(versions, dict) else {})
        except PanelApiError as error:
            if error.status in {"timeout", "offline", "other_error", "not_configured"}:
                raise

        if not isinstance(info, dict):
            raise PanelApiError("Системная информация панели имеет неверный формат")

        sip_registered = info.get("registerStatus")
        sip_failed = sip_registered is False or sip_registered == 0
        return {
            "status": "sip_auth_error" if sip_failed else "online",
            "response_time_ms": max(1, round((time.perf_counter() - started) * 1000)),
            "device_model": str(info.get("deviceModel") or info.get("model") or ""),
            "firmware_version": firmware,
            "temperature": info.get("temperature"),
            "supply_voltage": supply_voltage,
            "uptime_seconds": info.get("uptime"),
            "sip_registered": sip_registered,
            "reported_mac": str(info.get("mac") or "").upper(),
            "last_error": (
                "Панель доступна, но SIP-регистрация не выполнена"
                if sip_failed else ""
            ),
        }
    except PanelApiError as error:
        return {
            "status": error.status,
            "response_time_ms": None,
            "last_error": str(error),
        }
    finally:
        session.close()


def check_panel(
    panel: dict,
    *,
    attempts: int = TRANSIENT_CHECK_ATTEMPTS,
    retry_delay: float = TRANSIENT_RETRY_DELAY_SECONDS,
) -> dict:
    """Common resilient probe used by manual and background monitoring."""

    attempts = max(1, int(attempts))
    result: dict = {}
    for attempt in range(1, attempts + 1):
        result = _check_panel_once(panel)
        if result.get("status") not in {"timeout", "offline"} or attempt == attempts:
            result["attempts"] = attempt
            return result
        logger.info(
            "panel_check.retry panel_id=%s status=%s attempt=%s/%s",
            panel.get("id"), result.get("status"), attempt, attempts,
        )
        if retry_delay > 0:
            time.sleep(float(retry_delay))
    return result


def check_panel_api_connection() -> dict:
    """Check configured credentials against one enabled panel without persisting data."""

    if not panel_api_configured():
        return {
            "ok": False,
            "status": "not_configured",
            "message": "Логин или пароль API панелей не настроен",
            "panel_id": None,
            "panel_name": None,
            "response_time_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    from app.repositories.panel_repository import get_enabled_panels

    panel = next(
        (
            item
            for item in get_enabled_panels(0)
            if str(item.get("ip") or "").strip()
        ),
        None,
    )
    if not panel:
        return {
            "ok": False,
            "status": "not_configured",
            "message": "Нет включённой панели с IP-адресом для безопасной проверки",
            "panel_id": None,
            "panel_name": None,
            "response_time_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    result = check_panel(panel)
    common = {
        "panel_id": panel.get("id"),
        "panel_name": str(panel.get("name") or panel.get("address") or "Панель"),
        "response_time_ms": result.get("response_time_ms"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if result.get("status") == "online":
        return {
            "ok": True,
            "status": "ok",
            "message": "API панели доступен, авторизация выполнена успешно",
            **common,
        }
    safe_messages = {
        "sip_auth_error": "Панель доступна, но SIP-регистрация не выполнена",
        "offline": "Тестовая панель не ответила за отведённое время",
        "timeout": "Тестовая панель не ответила за отведённое время",
        "not_configured": "Реквизиты API панелей не настроены",
    }
    return {
        "ok": False,
        "status": str(result.get("status") or "error"),
        "message": safe_messages.get(
            str(result.get("status") or ""),
            "Проверка API панели завершилась ошибкой",
        ),
        **common,
    }


def get_panel_snapshot(panel: dict) -> tuple[bytes, str]:
    response, content, _ = _request(
        panel,
        "GET",
        "/camera/snapshot",
        expect_json=False,
    )
    content_type = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0]
    if not content_type.startswith("image/"):
        raise PanelApiError("API панели не вернул изображение")
    if not content:
        raise PanelApiError("Панель вернула пустой кадр")
    if len(content) > 8 * 1024 * 1024:
        raise PanelApiError("Размер кадра превышает 8 МБ")
    return content, content_type


def reboot_panel(panel: dict) -> None:
    _request(panel, "PUT", "/system/reboot")
