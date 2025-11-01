from __future__ import annotations

import logging
import time
from typing import Any, Callable

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


REQUEST_LATENCY = Histogram(
    "dswipe_request_latency_seconds",
    "HTTP request latency",
    labelnames=("method", "route"),
)
REQUEST_COUNT = Counter(
    "dswipe_request_total",
    "HTTP requests processed",
    labelnames=("method", "route", "status"),
)
IN_PROGRESS = Gauge(
    "dswipe_requests_in_progress",
    "Requests currently being processed",
    labelnames=("method", "route"),
)


def _resolve_route_path(request: Request) -> str:
    route = request.scope.get("route")
    if route and getattr(route, "path", None):
        return route.path
    return request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collects Prometheus-compatible metrics for each request."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        route_path = _resolve_route_path(request)
        labels = {"method": request.method, "route": route_path}

        IN_PROGRESS.labels(**labels).inc()
        start = time.perf_counter()
        response: Response | None = None

        try:
            response = await call_next(request)
            return response
        except Exception:
            raise
        finally:
            duration = time.perf_counter() - start
            status_code = str(response.status_code if response is not None else 500)

            REQUEST_LATENCY.labels(**labels).observe(duration)
            REQUEST_COUNT.labels(method=labels["method"], route=labels["route"], status=status_code).inc()
            IN_PROGRESS.labels(**labels).dec()


class SlowRequestMiddleware(BaseHTTPMiddleware):
    """Logs requests that exceed a response time threshold."""

    def __init__(self, app: Any, *, threshold_ms: float = 500.0) -> None:
        super().__init__(app)
        self.threshold_ms = threshold_ms

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0

        if duration_ms >= self.threshold_ms:
            logger.info(
                "slow_request",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )

        return response
