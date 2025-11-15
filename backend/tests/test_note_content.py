from __future__ import annotations

from typing import Any, Dict

import os
import sys

import pytest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.services import note_content


def test_augment_link_blocks_enriches_metadata(monkeypatch):
    captured: Dict[str, Any] = {}

    def fake_fetch(url: str) -> Dict[str, Any]:
        captured.setdefault("calls", []).append(url)
        return {
            "url": url,
            "title": "Example Title",
            "description": "Example Description",
            "image": "https://example.com/preview.png",
            "site_name": "Example",
        }

    monkeypatch.setattr(note_content, "fetch_ogp_metadata", fake_fetch)

    blocks = [
        {"type": "paragraph", "data": {"text": "hello"}},
        {"type": "link", "data": {"url": "https://example.com"}},
    ]

    enriched = note_content.augment_link_blocks(blocks)

    assert len(enriched) == 2
    link_block = enriched[1]
    assert link_block["data"].get("ogp", {}).get("title") == "Example Title"
    assert captured["calls"] == ["https://example.com"]


def test_augment_link_blocks_skips_invalid_urls(monkeypatch):
    monkeypatch.setattr(note_content, "fetch_ogp_metadata", lambda url: pytest.fail("Should not be called"))

    blocks = [
        {"type": "link", "data": {"url": "javascript:alert('xss')"}},
        {"type": "link", "data": {"url": ""}},
    ]

    enriched = note_content.augment_link_blocks(blocks)
    for block in enriched:
        assert "ogp" not in block.get("data", {})


def test_augment_link_blocks_caches_same_url(monkeypatch):
    call_count = {"value": 0}

    def fake_fetch(url: str) -> Dict[str, Any]:
        call_count["value"] += 1
        return {"url": url, "title": "", "description": "", "image": None, "site_name": ""}

    monkeypatch.setattr(note_content, "fetch_ogp_metadata", fake_fetch)

    blocks = [
        {"type": "link", "data": {"url": "https://example.com/a"}},
        {"type": "link", "data": {"url": "https://example.com/a"}},
    ]

    enriched = note_content.augment_link_blocks(blocks)
    assert len(enriched) == 2
    assert call_count["value"] == 1


def test_augment_link_blocks_preserves_thumbnail(monkeypatch):
    def fake_fetch(url: str) -> Dict[str, Any]:
        return {
            "url": url,
            "title": "OG Title",
            "description": "",
            "image": "https://example.com/og.png",
            "site_name": "Example",
        }

    monkeypatch.setattr(note_content, "fetch_ogp_metadata", fake_fetch)

    blocks = [
        {
            "type": "link",
            "data": {
                "url": "https://example.com",
                "thumbnailUrl": "https://cdn.example.com/custom.png",
            },
        }
    ]

    enriched = note_content.augment_link_blocks(blocks)
    link_block = enriched[0]
    assert link_block["data"].get("thumbnailUrl") == "https://cdn.example.com/custom.png"
    assert link_block["data"].get("ogp", {}).get("image") == "https://example.com/og.png"
