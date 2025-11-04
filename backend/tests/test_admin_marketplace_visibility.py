from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from app.routes import admin, products


class StubQuery:
    def __init__(self, supabase: "StubSupabase", table: str) -> None:
        self._supabase = supabase
        self._table = table
        self._eq_filters: Dict[str, Any] = {}
        self._in_filters: Dict[str, set[Any]] = {}
        self._order: List[tuple[str, bool]] = []
        self._range: Optional[tuple[int, int]] = None
        self._update_payload: Optional[Dict[str, Any]] = None
        self._insert_payload: Optional[List[Dict[str, Any]]] = None
        self._single = False
        self._count_requested = False

    def select(self, *args, **kwargs):
        if kwargs.get("count"):
            self._count_requested = True
        return self

    def eq(self, key: str, value: Any):
        self._eq_filters[key] = value
        return self

    def in_(self, key: str, values):
        self._in_filters[key] = {item for item in values if item is not None}
        return self

    def order(self, field: str, desc: bool = False):
        self._order.append((field, desc))
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def update(self, payload: Dict[str, Any]):
        self._update_payload = dict(payload)
        return self

    def insert(self, payload):
        if isinstance(payload, list):
            self._insert_payload = [dict(item) for item in payload]
        else:
            self._insert_payload = [dict(payload)]
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        table_rows = self._supabase.tables.get(self._table, [])

        def matches(row: Dict[str, Any]) -> bool:
            for key, value in self._eq_filters.items():
                if row.get(key) != value:
                    return False
            for key, values in self._in_filters.items():
                if not values:
                    return False
                if row.get(key) not in values:
                    return False
            return True

        matched_indices = [index for index, row in enumerate(table_rows) if matches(row)]

        if self._update_payload is not None:
            updated_rows = []
            for index in matched_indices:
                table_rows[index].update(self._update_payload)
                updated_rows.append(dict(table_rows[index]))
            data = updated_rows[0] if self._single else updated_rows
            return SimpleNamespace(data=data)

        if self._insert_payload is not None:
            self._supabase.tables.setdefault(self._table, [])
            self._supabase.tables[self._table].extend(self._insert_payload)
            data = self._insert_payload[0] if self._single else list(self._insert_payload)
            return SimpleNamespace(data=data)

        rows = [dict(table_rows[index]) for index in matched_indices]
        total_count = len(rows)

        for field, desc in reversed(self._order):
            rows.sort(key=lambda row: row.get(field), reverse=desc)

        if self._range:
            start, end = self._range
            rows = rows[start : end + 1]

        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None)

        result = SimpleNamespace(data=rows)
        if self._count_requested:
            result.count = total_count
        return result


class StubSupabase:
    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tables = tables

    def table(self, name: str) -> StubQuery:
        return StubQuery(self, name)


def _stub_now() -> str:
    return "2025-11-04T03:15:00+00:00"


@pytest.mark.asyncio
async def test_admin_forced_unpublish_hides_lp_from_marketplace(monkeypatch):
    tables: Dict[str, List[Dict[str, Any]]] = {
        "landing_pages": [
            {
                "id": "lp-1",
                "seller_id": "seller-1",
                "status": "published",
                "slug": "growth-lp",
                "title": "集客テンプレLP",
                "meta_image_url": None,
                "updated_at": "2025-11-04T00:00:00+00:00",
            }
        ],
        "products": [
            {
                "id": "prod-1",
                "seller_id": "seller-1",
                "lp_id": "lp-1",
                "product_type": "points",
                "title": "SNS講座",
                "description": "",
                "price_in_points": 500,
                "price_jpy": None,
                "allow_point_purchase": True,
                "allow_jpy_purchase": False,
                "tax_rate": 10.0,
                "tax_inclusive": True,
                "stock_quantity": None,
                "is_available": True,
                "is_featured": False,
                "total_sales": 0,
                "created_at": "2025-11-03T00:00:00+00:00",
                "updated_at": "2025-11-03T00:00:00+00:00",
            }
        ],
        "users": [
            {"id": "seller-1", "username": "creator"},
        ],
        "lp_steps": [],
        "moderation_events": [],
    }

    stub = StubSupabase(tables)

    monkeypatch.setattr(admin, "get_supabase", lambda: stub)
    monkeypatch.setattr(products, "get_supabase", lambda: stub)
    monkeypatch.setattr(admin, "create_moderation_event", lambda *_, **__: None)
    monkeypatch.setattr(admin, "now_utc_iso", _stub_now)

    request = admin.LPStatusUpdateRequest(status="archived", reason="policy_violation")
    await admin.update_lp_status("lp-1", request, admin={"id": "admin-1"})

    assert tables["landing_pages"][0]["status"] == "archived"
    assert tables["products"][0]["is_available"] is False

    public_response = await products.get_public_products(limit=5, offset=0, sort="latest", seller_username=None, lp_id=None, credentials=None)
    assert public_response.total == 0
    assert public_response.data == []

    # Re-enable to confirm toggling restores availability
    publish_request = admin.LPStatusUpdateRequest(status="published", reason=None)
    await admin.update_lp_status("lp-1", publish_request, admin={"id": "admin-1"})

    assert tables["landing_pages"][0]["status"] == "published"
    assert tables["products"][0]["is_available"] is True

    public_response_after = await products.get_public_products(limit=5, offset=0, sort="latest", seller_username=None, lp_id=None, credentials=None)
    assert public_response_after.total == 1
    assert len(public_response_after.data) == 1
    assert public_response_after.data[0].lp_slug == "growth-lp"
