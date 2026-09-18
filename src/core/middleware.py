import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.context import set_request_id

log = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = set_request_id()
        path = scope["path"]
        is_metrics = path == "/metrics"
        start = time.monotonic()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                if not is_metrics:
                    message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)

        if is_metrics:
            return

        duration_ms = round((time.monotonic() - start) * 1000)
        status_code = status_holder.get("status", 0)

        log_extra = {
            "http": {
                "method": scope["method"],
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            }
        }

        if status_code < 400:
            log.info("HTTP request completed", extra=log_extra)
        elif status_code < 500:
            log.warning("HTTP 4xx response", extra=log_extra)
        else:
            log.error("HTTP server error", extra=log_extra)
