"""Simple helper to enqueue background jobs using RQ."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from redis import Redis
from rq import Queue

from app.config import settings

logger = logging.getLogger(__name__)

_mail_queue: Optional[Queue] = None


def _get_mail_queue() -> Optional[Queue]:
    global _mail_queue
    if _mail_queue is not None:
        return _mail_queue
    if not settings.redis_url:
        return None
    try:
        connection = Redis.from_url(settings.redis_url)
    except Exception as exc:  # pragma: no cover - connection failure
        logger.error("Failed to connect to Redis for task queue: %s", exc)
        return None
    try:
        _mail_queue = Queue("mailgun", connection=connection, default_timeout=120)
    except Exception as exc:  # pragma: no cover - queue initialisation failure
        logger.error("Failed to initialise RQ queue: %s", exc)
        return None
    return _mail_queue


def enqueue_mailgun_send(payload: Dict[str, Any]) -> bool:
    """Enqueue a Mailgun delivery job. Returns True if queued successfully."""

    queue = _get_mail_queue()
    if not queue:
        return False
    try:
        queue.enqueue(
            "app.workers.mailgun_job.deliver_mailgun_message",
            kwargs=payload,
            job_timeout=120,
        )
        return True
    except Exception as exc:  # pragma: no cover - enqueue failure
        logger.error("Failed to enqueue Mailgun job: %s", exc)
        return False
