from __future__ import annotations

from typing import Optional

SUPPORTED_LOCALES = {"ja", "en"}
DEFAULT_LOCALE = "ja"


def normalize_locale(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_LOCALE
    normalized = str(value).strip().lower()
    return normalized if normalized in SUPPORTED_LOCALES else DEFAULT_LOCALE


def locale_path_prefix(locale: Optional[str]) -> str:
    normalized = normalize_locale(locale)
    return "" if normalized == "ja" else f"/{normalized}"
