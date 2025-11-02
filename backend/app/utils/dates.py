from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO formatted string into a timezone-aware datetime.

    Returns ``None`` when the input cannot be parsed.
    """

    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)
