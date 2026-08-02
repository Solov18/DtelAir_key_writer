from fastapi import Request
from fastapi.responses import JSONResponse, Response


ASYNC_DOCUMENT_HEADER = "KeyWriterAsync"


def async_document_response(
    request: Request,
    response: Response,
    *,
    url: str,
) -> Response:
    """Wrap rendered HTML for forms that manage their own loader lifecycle."""

    if request.headers.get("x-requested-with") != ASYNC_DOCUMENT_HEADER:
        return response

    body = getattr(response, "body", b"")
    html = body.decode("utf-8") if isinstance(body, bytes) else str(body or "")
    return JSONResponse(
        {
            "ok": True,
            "html": html,
            "url": url,
        }
    )
