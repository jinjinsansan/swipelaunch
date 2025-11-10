"""Utilities for enriching note content blocks and rich editor payloads."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

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


def _extract_access(item: Any) -> str:
    if not isinstance(item, dict):
        return "public"
    attrs = item.get("attrs")
    if isinstance(attrs, dict):
        access = attrs.get("access")
        if isinstance(access, str) and access in {"public", "paid"}:
            return access
    return "public"


def _filter_rich_node(node: Any, include_paid: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(node, dict):
        return None

    access = _extract_access(node)
    if access == "paid" and not include_paid:
        return None

    filtered: Dict[str, Any] = dict(node)

    content = node.get("content")
    if isinstance(content, list):
        filtered_children: List[Dict[str, Any]] = []
        for child in content:
            filtered_child = _filter_rich_node(child, include_paid)
            if filtered_child is not None:
                filtered_children.append(filtered_child)
        filtered["content"] = filtered_children

    marks = node.get("marks")
    if isinstance(marks, list):
        filtered_marks: List[Dict[str, Any]] = []
        for mark in marks:
            if not isinstance(mark, dict):
                continue
            mark_access = _extract_access(mark)
            if mark_access == "paid" and not include_paid:
                continue
            filtered_marks.append(dict(mark))
        filtered["marks"] = filtered_marks

    return filtered


def filter_rich_content(rich_content: Optional[Dict[str, Any]], include_paid: bool) -> Optional[Dict[str, Any]]:
    """Filter rich editor JSONContent based on access level."""

    if not isinstance(rich_content, dict):
        return None

    filtered = _filter_rich_node(rich_content, include_paid)
    if filtered is None:
        return {"type": rich_content.get("type", "doc"), "content": []}
    return filtered


__all__ = ["augment_link_blocks", "filter_rich_content"]


__all__ = ["augment_link_blocks"]
