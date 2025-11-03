"""Utilities for fetching and caching Open Graph metadata."""

from __future__ import annotations

import logging
import re
import threading
import time
from html import unescape
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

import httpx


logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
_CACHE_MAX_SIZE = 256
_REQUEST_TIMEOUT = 6.0

_cache: Dict[str, tuple[float, Dict[str, Optional[str]]]] = {}
_cache_lock = threading.Lock()


_META_TAG_REGEX_TEMPLATE = r"<meta[^>]+{attr}\s*=\s*\"{name}\"[^>]*>"
_CONTENT_REGEX = re.compile(r"content\s*=\s*\"([^\"]+)\"", re.IGNORECASE)
_TITLE_REGEX = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DSwipeBot/1.0; +https://d-swipe.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
}


def normalize_url(url: str) -> Optional[str]:
    """Normalize a URL and ensure it is an http(s) link."""

    if not isinstance(url, str):
        return None

    candidate = url.strip()
    if not candidate:
        return None

    parsed = urlparse(candidate, scheme="")
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None

    sanitized = parsed._replace(fragment="")
    return urlunparse(sanitized)


def _set_cache(url: str, payload: Dict[str, Optional[str]]) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_SIZE:
            # Remove the oldest entry
            oldest_key = min(_cache.items(), key=lambda item: item[1][0])[0]
            _cache.pop(oldest_key, None)
        _cache[url] = (time.time(), payload)


def _get_cache(url: str) -> Optional[Dict[str, Optional[str]]]:
    with _cache_lock:
        entry = _cache.get(url)
        if not entry:
            return None
        timestamp, payload = entry
        if time.time() - timestamp > _CACHE_TTL_SECONDS:
            _cache.pop(url, None)
            return None
        return payload


def _extract_meta_tag(html: str, name: str, attr: str = "property") -> Optional[str]:
    pattern = re.compile(_META_TAG_REGEX_TEMPLATE.format(attr=attr, name=re.escape(name)), re.IGNORECASE)
    match = pattern.search(html)
    if not match:
        return None

    tag = match.group(0)
    content_match = _CONTENT_REGEX.search(tag)
    if not content_match:
        return None
    value = unescape(content_match.group(1) or "").strip()
    return value or None


def _extract_fallback_title(html: str) -> Optional[str]:
    match = _TITLE_REGEX.search(html)
    if not match:
        return None
    text = unescape(match.group(1) or "").strip()
    return text or None


def _is_valid_image_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    normalized = normalize_url(url)
    return normalized


def fetch_ogp_metadata(url: str) -> Dict[str, Optional[str]]:
    """Fetch OGP metadata for a URL, returning cached results when possible."""

    normalized = normalize_url(url)
    if not normalized:
        return {
            "url": None,
            "title": "",
            "description": "",
            "image": None,
            "site_name": "",
        }

    cached = _get_cache(normalized)
    if cached is not None:
        return cached

    metadata: Dict[str, Optional[str]] = {
        "url": normalized,
        "title": "",
        "description": "",
        "image": None,
        "site_name": "",
    }

    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT, headers=_DEFAULT_HEADERS, follow_redirects=True) as client:
            response = client.get(normalized)
            response.raise_for_status()
            html = response.text[:200_000]
    except httpx.HTTPError as exc:
        logger.debug("OGP fetch failed for %s: %s", normalized, exc)
    else:
        title = (
            _extract_meta_tag(html, "og:title")
            or _extract_meta_tag(html, "twitter:title")
            or _extract_fallback_title(html)
        )
        description = (
            _extract_meta_tag(html, "og:description")
            or _extract_meta_tag(html, "description", attr="name")
            or _extract_meta_tag(html, "twitter:description")
        )
        image = (
            _extract_meta_tag(html, "og:image")
            or _extract_meta_tag(html, "og:image:secure_url")
            or _extract_meta_tag(html, "twitter:image")
        )
        site_name = (
            _extract_meta_tag(html, "og:site_name")
            or _extract_meta_tag(html, "application-name", attr="name")
        )

        metadata.update(
            {
                "title": title or "",
                "description": description or "",
                "image": _is_valid_image_url(image),
                "site_name": site_name or "",
            }
        )

    _set_cache(normalized, metadata)
    return metadata


__all__ = ["fetch_ogp_metadata", "normalize_url"]
