from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.constants.subscription_plans import SUBSCRIPTION_PLANS
from app.routes import purchase_history


class FakeQuery:
    def __init__(self, supabase: "FakeSupabase", table: str) -> None:
        self._supabase = supabase
        self._table = table
        self._count: str | None = None
        self._eq_filters: dict[str, str] = {}
        self._in_filters: dict[str, set[str]] = {}
        self._order_field: str | None = None
        self._order_desc: bool = False
        self._range: tuple[int, int] | None = None

    def select(self, *_args, count: str | None = None, **_kwargs):
        self._count = count
        return self

    def eq(self, key: str, value: str):
        self._eq_filters[key] = value
        return self

    def in_(self, key: str, values):
        self._in_filters[key] = {v for v in values if v}
        return self

    def order(self, field: str, desc: bool = False):
        self._order_field = field
        self._order_desc = desc
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self._supabase.tables.get(self._table, []))

        # apply equality filters
        filtered = []
        for row in rows:
            if all(row.get(key) == value for key, value in self._eq_filters.items()):
                filtered.append(row)

        # apply IN filters
        for key, values in self._in_filters.items():
            if not values:
                filtered = []
                break
            filtered = [row for row in filtered if row.get(key) in values]

        total_count = len(filtered)

        if self._order_field:
            filtered.sort(key=lambda item: item.get(self._order_field), reverse=self._order_desc)

        if self._range:
            start, end = self._range
            filtered = filtered[start : end + 1]

        result = SimpleNamespace(data=[dict(row) for row in filtered])
        if self._count == "exact":
            result.count = total_count
        return result


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def setup_module(_: object) -> None:
    purchase_history.router.dependency_overrides = {}


def test_purchase_history_aggregates(monkeypatch):
    plan = SUBSCRIPTION_PLANS[0]
    tables = {
        "point_transactions": [
            {
                "id": "tx-1",
                "user_id": "user-123",
                "transaction_type": "product_purchase",
                "related_product_id": "product-1",
                "amount": -500,
                "description": "LP商品を購入",
                "created_at": "2025-01-05T10:00:00Z",
            },
        ],
        "products": [
            {
                "id": "product-1",
                "title": "SNS集客テンプレート",
                "seller_id": "seller-1",
                "lp_id": "lp-1",
            }
        ],
        "landing_pages": [
            {"id": "lp-1", "slug": "sns-growth"},
        ],
        "users": [
            {
                "id": "seller-1",
                "username": "seller",
                "display_name": "セラー",
                "profile_image_url": "https://example.com/avatar.jpg",
            },
            {
                "id": "author-1",
                "username": "writer",
                "display_name": "ライター",
            },
            {
                "id": "owner-1",
                "username": "salonboss",
                "display_name": "サロン代表",
            },
        ],
        "note_purchases": [
            {
                "id": "note-purchase-1",
                "note_id": "note-1",
                "buyer_id": "user-123",
                "points_spent": 300,
                "purchased_at": "2025-01-06T12:00:00Z",
            }
        ],
        "notes": [
            {
                "id": "note-1",
                "author_id": "author-1",
                "title": "勝てるLPコピーの作り方",
                "slug": "winning-copy",
                "cover_image_url": "https://example.com/note.jpg",
            }
        ],
        "salon_memberships": [
            {
                "id": "membership-1",
                "salon_id": "salon-1",
                "user_id": "user-123",
                "status": "ACTIVE",
                "joined_at": "2025-01-03T09:00:00Z",
                "last_charged_at": "2025-01-03T09:00:00Z",
                "next_charge_at": "2025-02-03T09:00:00Z",
            }
        ],
        "salons": [
            {
                "id": "salon-1",
                "title": "週次競馬サロン",
                "category": "競馬",
                "thumbnail_url": "https://example.com/salon.jpg",
                "owner_id": "owner-1",
                "subscription_plan_id": plan.subscription_plan_id,
            }
        ],
    }

    fake = FakeSupabase(tables)

    monkeypatch.setattr(purchase_history, "get_supabase", lambda: fake)
    monkeypatch.setattr(purchase_history, "get_current_user_id", lambda _cred: "user-123")

    app = FastAPI()
    app.include_router(purchase_history.router, prefix="/api")
    app.dependency_overrides[purchase_history.security] = _override_security

    client = TestClient(app)
    response = client.get("/api/purchases/history")

    assert response.status_code == 200
    payload = response.json()

    assert payload["summary"]["product_purchases"] == 1
    assert payload["summary"]["note_purchases"] == 1
    assert payload["summary"]["active_salon_memberships"] == 1

    product = payload["products"][0]
    assert product["product_title"] == "SNS集客テンプレート"
    assert product["amount_points"] == 500
    assert product["seller_username"] == "seller"
    assert product["lp_slug"] == "sns-growth"

    note = payload["notes"][0]
    assert note["note_title"] == "勝てるLPコピーの作り方"
    assert note["author_username"] == "writer"
    assert note["points_spent"] == 300

    salon = payload["active_salons"][0]
    assert salon["salon_title"] == "週次競馬サロン"
    assert salon["plan_label"] == plan.label
    assert salon["status"] == "ACTIVE"
