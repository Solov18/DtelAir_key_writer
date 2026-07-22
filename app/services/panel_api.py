import time
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from app.settings import settings


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


def _http_request(method: str, url: str, **kwargs) -> requests.Response:
    """Send panel requests directly, without workstation proxy settings."""
    session = requests.Session()
    session.trust_env = False
    try:
        return session.request(method, url, **kwargs)
    finally:
        session.close()


def _request(
    panel: dict,
    method: str,
    path: str,
    *,
    expect_json: bool = True,
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
            auth=HTTPBasicAuth(
                settings.panel_api_login.strip(),
                settings.panel_api_password,
            ),
            headers={"Accept": "application/json"},
            timeout=max(0.5, float(settings.panel_api_timeout)),
        )
    except requests.Timeout as error:
        raise PanelApiError("Панель не ответила за отведённое время", "offline") from error
    except requests.RequestException as error:
        raise PanelApiError("Нет соединения с панелью", "offline") from error

    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    if response.status_code == 401:
        raise PanelApiError("Панель отклонила логин или пароль", "auth_error")
    if response.status_code >= 400:
        raise PanelApiError(
            f"API панели вернул HTTP {response.status_code}",
            "error",
        )

    if not expect_json:
        return response, response.content, elapsed_ms

    try:
        payload = response.json() if response.content else {}
    except ValueError as error:
        raise PanelApiError("Панель вернула некорректный ответ", "error") from error
    return response, payload, elapsed_ms


def _firmware_name(payload: dict) -> str:
    for section in ("opt", "rootfs", "media"):
        value = payload.get(section)
        if isinstance(value, dict) and value.get("name"):
            return str(value["name"])
    return ""


def check_panel(panel: dict) -> dict:
    started = time.perf_counter()
    try:
        _, info, _ = _request(panel, "GET", "/system/info")
        supply_voltage = None
        try:
            _, mcu_info, _ = _request(panel, "GET", "/v1/mcu/info")
            if isinstance(mcu_info, dict):
                power = mcu_info.get("power")
                if isinstance(power, dict):
                    supply_voltage = power.get("dc")
        except PanelApiError as error:
            if error.status in {"auth_error", "offline", "not_configured"}:
                raise

        firmware = ""
        try:
            _, versions, _ = _request(panel, "GET", "/v2/system/versions")
            firmware = _firmware_name(versions if isinstance(versions, dict) else {})
        except PanelApiError as error:
            if error.status in {"auth_error", "offline", "not_configured"}:
                raise

        if not isinstance(info, dict):
            raise PanelApiError("Системная информация панели имеет неверный формат")

        return {
            "status": "online",
            "response_time_ms": max(1, round((time.perf_counter() - started) * 1000)),
            "device_model": str(info.get("deviceModel") or info.get("model") or ""),
            "firmware_version": firmware,
            "temperature": info.get("temperature"),
            "supply_voltage": supply_voltage,
            "uptime_seconds": info.get("uptime"),
            "sip_registered": info.get("registerStatus"),
            "reported_mac": str(info.get("mac") or "").upper(),
            "last_error": "",
        }
    except PanelApiError as error:
        return {
            "status": error.status,
            "response_time_ms": None,
            "last_error": str(error),
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
