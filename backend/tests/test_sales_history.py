from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.routes import sales_history


class FakeQuery:
    def __init__(self, supabase: "FakeSupabase", table: str) -> None:
        self._supabase = supabase
        self._table = table
        self._select: tuple | None = None
        self._eq_filters: dict[str, Any] = {}
        self._in_filters: dict[str, set[Any]] = {}
        self._gt_filters: dict[str, Any] = {}
        self._order_field: tuple[str, bool] | None = None
        self._range: tuple[int, int] | None = None

    def select(self, *args, **kwargs):
        self._select = args
        return self

    def eq(self, key: str, value: Any):
        self._eq_filters[key] = value
        return self

    def in_(self, key: str, values):
        self._in_filters[key] = {item for item in values if item is not None}
        return self

    def gt(self, key: str, value: Any):
        self._gt_filters[key] = value
        return self

    def order(self, field: str, desc: bool = False):
        self._order_field = (field, desc)
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def execute(self):
        rows = [dict(row) for row in self._supabase.tables.get(self._table, [])]

        # Apply equality filters
        for key, value in self._eq_filters.items():
            rows = [row for row in rows if row.get(key) == value]

        # Apply IN filters
        for key, values in self._in_filters.items():
            if not values:
                rows = []
                break
            rows = [row for row in rows if row.get(key) in values]

        # Apply greater-than filters
        for key, value in self._gt_filters.items():
            rows = [row for row in rows if row.get(key) is not None and row.get(key) > value]

        total_count = len(rows)

        # Apply ordering
        if self._order_field:
            field, desc = self._order_field
            rows.sort(key=lambda row: row.get(field), reverse=desc)

        # Apply range slicing (inclusive)
        if self._range:
            start, end = self._range
            rows = rows[start : end + 1]

        result = SimpleNamespace(data=rows)
        result.count = total_count
        return result


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def setup_module(_: object) -> None:
    sales_history.router.dependency_overrides = {}


def test_sales_history_aggregates(monkeypatch):
    tables = {
        "users": [
            {"id": "seller-1", "username": "seller", "user_type": "seller"},
            {"id": "buyer-1", "username": "buyer_one", "profile_image_url": "https://example.com/b1.png"},
            {"id": "buyer-2", "username": "buyer_two", "profile_image_url": "https://example.com/b2.png"},
        ],
        "products": [
            {"id": "product-1", "title": "SNS講座テンプレート", "lp_id": "lp-1", "seller_id": "seller-1"},
        ],
        "notes": [
            {"id": "note-1", "title": "即売れNOTE", "slug": "note-sell", "author_id": "seller-1"},
        ],
        "salons": [
            {"id": "salon-1", "title": "月額マーケ講座", "owner_id": "seller-1"},
        ],
        "landing_pages": [
            {"id": "lp-1", "slug": "lp-template"},
        ],
        "point_transactions": [
            {
                "id": "pt-1",
                "user_id": "buyer-1",
                "transaction_type": "product_purchase",
                "related_product_id": "product-1",
                "amount": -500,
                "description": "SNS講座テンプレート x1を購入",
                "created_at": "2025-01-01T10:00:00Z",
            },
        ],
        "payment_orders": [
            {
                "id": "po-1",
                "user_id": "buyer-2",
                "seller_id": "seller-1",
                "item_type": "product",
                "item_id": "product-1",
                "amount_jpy": 4500,
                "status": "COMPLETED",
                "payment_method": "yen",
                "completed_at": "2025-01-02T09:00:00Z",
            },
            {
                "id": "po-2",
                "user_id": "buyer-1",
                "seller_id": "seller-1",
                "item_type": "note",
                "item_id": "note-1",
                "amount_jpy": 1200,
                "status": "COMPLETED",
                "payment_method": "yen",
                "completed_at": "2025-01-03T09:30:00Z",
            },
        ],
        "note_purchases": [
            {
                "id": "np-1",
                "note_id": "note-1",
                "buyer_id": "buyer-2",
                "points_spent": 300,
                "purchased_at": "2025-01-01T12:00:00Z",
            },
        ],
        "salon_memberships": [
            {
                "id": "sm-1",
                "salon_id": "salon-1",
                "user_id": "buyer-1",
                "status": "ACTIVE",
                "joined_at": "2025-01-04T09:00:00Z",
                "next_charge_at": "2025-02-04T09:00:00Z",
                "last_charged_at": "2025-01-04T09:00:00Z",
            },
        ],
    }

    fake = FakeSupabase(tables)

    monkeypatch.setattr(sales_history, "get_supabase", lambda: fake)
    monkeypatch.setattr(sales_history, "_get_current_user", lambda _cred: {"id": "seller-1", "user_type": "seller"})

    app = FastAPI()
    app.include_router(sales_history.router, prefix="/api")
    app.dependency_overrides[sales_history.security] = _override_security

    client = TestClient(app)
    response = client.get("/api/sales/history")

    assert response.status_code == 200
    payload = response.json()

    summary = payload["summary"]
    assert summary["product_orders"] == 2
    assert summary["note_orders"] == 2
    assert summary["salon_memberships"] == 1
    assert summary["total_points_revenue"] == 800
    assert summary["total_yen_revenue"] == 5700

    products = payload["products"]
    assert products[0]["payment_method"] == "yen"
    assert products[0]["amount_jpy"] == 4500
    assert products[1]["amount_points"] == 500
    assert products[1]["buyer_username"] == "buyer_one"

    notes = payload["notes"]
    assert {note["payment_method"] for note in notes} == {"points", "yen"}

    salons = payload["salons"]
    assert salons[0]["salon_title"] == "月額マーケ講座"
    assert salons[0]["buyer_username"] == "buyer_one"
