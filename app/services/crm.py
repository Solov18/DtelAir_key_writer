import json

import requests

from app.settings import settings


def crm_add_key(
    mac: str,
    hex_value: str,
    flat_num: str,
    inner: int,
):
    url = f"{settings.crm_base_url.rstrip('/')}/front/device-keys/{mac}/create-key"

    payload = {
        "value": hex_value,
        "numberSystem": "16",
        "flatNum": flat_num or "0",
        "inner": int(inner),
    }

    if settings.dry_run:
        return {
            "ok": True,
            "status": "DRY_RUN",
            "response": json.dumps(
                {
                    "url": url,
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
        }

    if not settings.crm_cookie:
        return {
            "ok": False,
            "status": "NO_COOKIE",
            "response": "CRM_COOKIE пустой в .env",
        }

    try:
        response = requests.post(
            url,
            headers={
                "Cookie": settings.crm_cookie,
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=settings.request_timeout,
        )

        ok = "true" in response.text.lower()

        return {
            "ok": ok,
            "status": str(response.status_code),
            "response": response.text[:1000],
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "ERROR",
            "response": str(error),
        }