from __future__ import annotations

import logging
import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


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
