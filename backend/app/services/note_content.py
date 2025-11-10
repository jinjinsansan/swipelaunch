"""Utilities for enriching note content blocks."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.ogp import fetch_ogp_metadata, normalize_url


def _to_block_dict(block: Any) -> Dict[str, Any]:
    if isinstance(block, dict):
        return dict(block)
    if hasattr(block, "dict") and callable(getattr(block, "dict")):
        return block.dict()  # type: ignore[return-value]
    return {
        "type": getattr(block, "type", "paragraph"),
        "data": getattr(block, "data", {}) or {},
        "access": getattr(block, "access", "public"),
        "id": getattr(block, "id", None),
    }


def augment_link_blocks(blocks: Iterable[Any]) -> List[Dict[str, Any]]:
    """Return a copy of blocks enriched with OGP metadata for link blocks."""

    if not blocks:
        return []

    cache: Dict[str, Dict[str, Any]] = {}
    enriched: List[Dict[str, Any]] = []

    for raw_block in blocks:
        block = _to_block_dict(raw_block)
        data = dict(block.get("data") or {})

        url_value = data.get("url")
        if isinstance(url_value, str):
            normalized = normalize_url(url_value)
            if normalized:
                metadata = cache.get(normalized)
                if metadata is None:
                    metadata = fetch_ogp_metadata(normalized)
                    cache[normalized] = metadata
                if metadata:
                    data["ogp"] = metadata

        block["data"] = data
        enriched.append(block)

    return enriched


__all__ = ["augment_link_blocks"]
