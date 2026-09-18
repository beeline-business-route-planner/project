import time

from prometheus_client import Counter, Gauge, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

active_requests = Gauge(
    "http_requests_active",
    "Active HTTP requests",
    ["method"],
)


def _route_path(scope: Scope) -> str:
    route = scope.get("route")
    if route and hasattr(route, "path"):
        return route.path
    return "/unknown"


class PrometheusMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        active_requests.labels(method=method).inc()

        try:
            start = time.perf_counter()
            await self.app(scope, receive, send_wrapper)
            duration = time.perf_counter() - start

            path = _route_path(scope)

            http_requests_total.labels(
                method=method,
                path=path,
                status=status_holder.get("status", 0),
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                path=path,
            ).observe(duration)

        finally:
            active_requests.labels(method=method).dec()
