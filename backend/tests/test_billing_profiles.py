import os
import sys
from datetime import datetime
from types import SimpleNamespace
from typing import Dict

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import payments


app = FastAPI()
app.include_router(payments.router, prefix="/api")


class FakeSupabase:
    def __init__(self):
        self.storage = {}

    def seed(self, table: str, rows):
        self.storage[table] = [dict(row) for row in rows]

    def table(self, name: str):  # pragma: no cover - executed via query builder
        return FakeQuery(self, name)


class FakeQuery:
    def __init__(self, parent: FakeSupabase, table: str):
        self.parent = parent
        self.table = table
        self.operation = None
        self.criteria = {}
        self.payload = None
        self.expect_single = False
        self.ordering = None
        self.limit_value = None

    def select(self, _columns: str):
        self.operation = "select"
        return self

    def upsert(self, payload, on_conflict=None):
        self.operation = ("upsert", on_conflict)
        self.payload = payload
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def order(self, column: str, desc: bool = False):  # pragma: no cover - simple ordering helper
        self.ordering = (column, desc)
        return self

    def limit(self, value: int):  # pragma: no cover - simple limit helper
        self.limit_value = value
        return self

    def eq(self, column: str, value):
        self.criteria[column] = value
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def maybe_single(self):
        self.expect_single = True
        return self

    def single(self):
        self.expect_single = True
        return self

    def execute(self):
        if self.operation == "select":
            rows = [dict(row) for row in self.parent.storage.get(self.table, [])]
            for key, value in self.criteria.items():
                rows = [row for row in rows if row.get(key) == value]
            if self.ordering:
                column, desc = self.ordering
                rows.sort(key=lambda row: row.get(column), reverse=desc)
            if self.limit_value is not None:
                rows = rows[: self.limit_value]
            if self.expect_single:
                data = rows[0] if rows else None
                return SimpleNamespace(data=data)
            return SimpleNamespace(data=rows)

        if isinstance(self.operation, tuple) and self.operation[0] == "upsert":
            on_conflict = self.operation[1]
            payload = dict(self.payload)
            storage = self.parent.storage.setdefault(self.table, [])

            key = on_conflict or "id"
            value = payload.get(key)
            stored = None
            if value is not None:
                for index, row in enumerate(storage):
                    if row.get(key) == value:
                        stored = {**row, **payload}
                        storage[index] = stored
                        break
            if stored is None:
                stored = {
                    **payload,
                    "created_at": payload.get("created_at") or "2025-01-01T00:00:00Z",
                }
                storage.append(stored)
            stored.setdefault("updated_at", payload.get("updated_at") or "2025-01-01T00:00:00Z")
            return SimpleNamespace(data=[stored])

        if self.operation == "insert":
            storage = self.parent.storage.setdefault(self.table, [])
            payload = self.payload
            if isinstance(payload, list):
                rows = [dict(row) for row in payload]
            else:
                rows = [dict(payload)]
            storage.extend(rows)
            return SimpleNamespace(data=rows)

        if self.operation == "delete":
            storage = self.parent.storage.get(self.table, [])
            if not storage:
                return SimpleNamespace(data=None)
            remaining = []
            for row in storage:
                match = True
                for key, value in self.criteria.items():
                    if row.get(key) != value:
                        match = False
                        break
                if not match:
                    remaining.append(row)
            self.parent.storage[self.table] = remaining
            return SimpleNamespace(data=None)

        raise AssertionError("Unsupported operation")


def _override_credentials():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="dummy-token")


def setup_module(_: object):
    app.dependency_overrides[payments.security] = _override_credentials


def teardown_module(_: object):
    app.dependency_overrides.pop(payments.security, None)


def _install_supabase(monkeypatch, supabase_instance):
    monkeypatch.setattr(payments, "get_supabase", lambda: supabase_instance)
    monkeypatch.setattr(payments, "decode_access_token", lambda token: {"sub": "user-123"})


def test_get_billing_profile_empty(monkeypatch):
    supabase = FakeSupabase()
    _install_supabase(monkeypatch, supabase)
    client = TestClient(app)

    response = client.get("/api/payments/billing-profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "user-123"
    assert payload["profile"] is None
    assert payload["updated_at"] is None


def test_upsert_and_get_billing_profile(monkeypatch):
    supabase = FakeSupabase()
    supabase.seed("billing_profiles", [])
    _install_supabase(monkeypatch, supabase)
    client = TestClient(app)

    upsert_response = client.put(
        "/api/payments/billing-profile",
        json={
            "full_name": "山田 太郎",
            "email": "taro@example.com",
            "phone_number": "09012345678",
            "postal_code": "123-4567",
            "prefecture": "東京都",
            "city": "渋谷区",
            "address_line1": "神南1-1-1",
        },
    )

    assert upsert_response.status_code == 200
    upsert_payload = upsert_response.json()
    assert upsert_payload["profile"]["full_name"] == "山田 太郎"
    assert upsert_payload["profile"]["email"] == "taro@example.com"
    assert upsert_payload["profile"]["phone_number"] == "09012345678"
    assert upsert_payload["profile"]["country_code"] == "JP"

    get_response = client.get("/api/payments/billing-profile")
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["profile"]["city"] == "渋谷区"
    assert get_payload["profile"]["prefecture"] == "東京都"


def test_delete_billing_profile(monkeypatch):
    supabase = FakeSupabase()
    supabase.seed("billing_profiles", [
        {
            "user_id": "user-123",
            "full_name": "削除対象",
            "email": "delete@example.com",
            "phone_number": "0000",
            "updated_at": "2025-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
        }
    ])
    _install_supabase(monkeypatch, supabase)
    client = TestClient(app)

    response = client.delete("/api/payments/billing-profile")

    assert response.status_code == 204
    assert supabase.storage["billing_profiles"] == []

    get_response = client.get("/api/payments/billing-profile")
    assert get_response.status_code == 200
    assert get_response.json()["profile"] is None


def test_quick_checkout_requires_profile(monkeypatch):
    supabase = FakeSupabase()
    _install_supabase(monkeypatch, supabase)
    client = TestClient(app)

    def _raise_profile_error(*_: object, **__: object):
        raise HTTPException(status_code=400, detail="請求先情報を設定してください")

    monkeypatch.setattr(payments, "_require_billing_profile", _raise_profile_error)

    response = client.post(
        "/api/payments/quick-checkout",
        json={"item_type": "note", "item_id": "note-1"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "請求先情報を設定してください"


def test_quick_checkout_note_success(monkeypatch):
    supabase = FakeSupabase()
    supabase.seed("billing_profiles", [
        {
            "user_id": "user-123",
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone_number": "PHONE_NUMBER",
            "updated_at": "2025-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
        }
    ])
    supabase.seed("users", [
        {
            "id": "user-123",
            "email": "john@example.com",
            "username": "john",
            "preferred_locale": "ja",
        }
    ])
    supabase.seed("notes", [
        {
            "id": "note-1",
            "author_id": "author-1",
            "slug": "note-1",
            "title": "Note Title",
            "price_jpy": 1200,
            "allow_jpy_purchase": True,
        }
    ])
    supabase.seed("payment_orders", [])

    async def _create_checkout_preference(**_: object) -> Dict[str, str]:  # type: ignore[override]
        return {"checkout_url": "quick-note-url", "id": "pref_test_1"}

    monkeypatch.setattr(payments, "get_supabase", lambda: supabase)
    monkeypatch.setattr(payments.one_lat_client, "create_checkout_preference", _create_checkout_preference)
    monkeypatch.setattr(payments, "decode_access_token", lambda token: {"sub": "user-123"})
    monkeypatch.setattr(payments.settings, "backend_public_url", "backend-public-url")
    monkeypatch.setattr(payments.settings, "frontend_url", "frontend-public-url")
    monkeypatch.setattr(payments, "get_platform_settings", lambda: SimpleNamespace(effective_exchange_rate=150.0))

    client = TestClient(app)
    response = client.post(
        "/api/payments/quick-checkout",
        json={"item_type": "note", "item_id": "note-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkout_url"] == "quick-note-url"
    assert payload["item_type"] == "note"
    order = supabase.storage["payment_orders"][0]
    assert order["item_id"] == "note-1"
    assert order["metadata"]["quick_checkout"] is True
    assert order["metadata"]["checkout_url"] == "quick-note-url"
    assert "generated_at" in order["metadata"]


def test_quick_checkout_note_reuses_recent_order(monkeypatch):
    supabase = FakeSupabase()
    supabase.seed("billing_profiles", [
        {
            "user_id": "user-123",
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone_number": "PHONE_NUMBER",
            "updated_at": "2025-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
        }
    ])
    supabase.seed("users", [
        {
            "id": "user-123",
            "email": "john@example.com",
            "username": "john",
            "preferred_locale": "ja",
        }
    ])
    supabase.seed("payment_orders", [
        {
            "user_id": "user-123",
            "seller_id": "author-1",
            "item_type": "note",
            "item_id": "note-1",
            "payment_method": "yen",
            "status": "PENDING",
            "external_id": "note_quick_existing",
            "metadata": {"quick_checkout": True, "checkout_url": "reused-note-url"},
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
    ])

    monkeypatch.setattr(payments, "get_supabase", lambda: supabase)
    monkeypatch.setattr(payments, "decode_access_token", lambda token: {"sub": "user-123"})

    called = {"count": 0}

    async def _create_checkout_preference(**_: object) -> Dict[str, str]:  # type: ignore[override]
        called["count"] += 1
        return {"checkout_url": "should-not-be-used", "id": "pref_should_not"}

    monkeypatch.setattr(payments.one_lat_client, "create_checkout_preference", _create_checkout_preference)

    client = TestClient(app)
    response = client.post(
        "/api/payments/quick-checkout",
        json={"item_type": "note", "item_id": "note-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkout_url"] == "reused-note-url"
    assert payload["item_type"] == "note"
    assert called["count"] == 0
    assert len(supabase.storage["payment_orders"]) == 1


def test_quick_checkout_product_success(monkeypatch):
    supabase = FakeSupabase()
    supabase.seed("billing_profiles", [
        {
            "user_id": "user-123",
            "full_name": "John Doe",
            "email": "john@example.com",
            "updated_at": "2025-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
        }
    ])
    supabase.seed("users", [
        {
            "id": "user-123",
            "email": "john@example.com",
            "username": "john",
            "preferred_locale": "ja",
        }
    ])
    supabase.seed("products", [
        {
            "id": "product-1",
            "title": "Product",
            "seller_id": "seller-1",
            "price_jpy": 1500,
            "allow_jpy_purchase": True,
            "stock_quantity": 5,
        }
    ])
    supabase.seed("payment_orders", [])

    async def _create_checkout_preference(**_: object) -> Dict[str, str]:  # type: ignore[override]
        return {"checkout_url": "quick-product-url", "id": "pref_test_2"}

    monkeypatch.setattr(payments, "get_supabase", lambda: supabase)
    monkeypatch.setattr(payments.one_lat_client, "create_checkout_preference", _create_checkout_preference)
    monkeypatch.setattr(payments, "decode_access_token", lambda token: {"sub": "user-123"})
    monkeypatch.setattr(payments.settings, "backend_public_url", "backend-public-url")
    monkeypatch.setattr(payments.settings, "frontend_url", "frontend-public-url")
    monkeypatch.setattr(payments, "get_platform_settings", lambda: SimpleNamespace(effective_exchange_rate=150.0))

    client = TestClient(app)
    response = client.post(
        "/api/payments/quick-checkout",
        json={"item_type": "product", "item_id": "product-1", "quantity": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkout_url"] == "quick-product-url"
    assert payload["item_type"] == "product"
    order = supabase.storage["payment_orders"][0]
    assert order["item_id"] == "product-1"
    assert order["metadata"]["quantity"] == 2
    assert order["metadata"]["checkout_url"] == "quick-product-url"
    assert "generated_at" in order["metadata"]


def test_quick_checkout_subscription_success(monkeypatch):
    supabase = FakeSupabase()
    supabase.seed("billing_profiles", [
        {
            "user_id": "user-123",
            "full_name": "John Doe",
            "email": "john@example.com",
            "updated_at": "2025-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
        }
    ])
    supabase.seed("users", [
        {
            "id": "user-123",
            "email": "john@example.com",
            "username": "john",
            "preferred_locale": "ja",
        }
    ])
    supabase.seed("one_lat_subscription_sessions", [])

    async def _create_checkout_preference(**_: object) -> Dict[str, str]:  # type: ignore[override]
        return {"checkout_url": "quick-subscription-url", "id": "pref_test_3"}

    monkeypatch.setattr(payments, "get_supabase", lambda: supabase)
    monkeypatch.setattr(payments.one_lat_client, "create_checkout_preference", _create_checkout_preference)
    monkeypatch.setattr(payments, "decode_access_token", lambda token: {"sub": "user-123"})
    monkeypatch.setattr(payments.settings, "backend_public_url", "backend-public-url")
    monkeypatch.setattr(payments.settings, "frontend_url", "frontend-public-url")
    monkeypatch.setattr(payments, "get_platform_settings", lambda: SimpleNamespace(effective_exchange_rate=150.0))
    monkeypatch.setattr(
        payments,
        "get_subscription_plan",
        lambda _: SimpleNamespace(
            key="test_plan",
            usd_amount=10.0,
            subscription_plan_id="plan_test",
            points=100,
            label="Test Plan",
        ),
    )

    client = TestClient(app)
    response = client.post(
        "/api/payments/quick-checkout",
        json={"item_type": "subscription", "plan_key": "test_plan"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkout_url"] == "quick-subscription-url"
    assert payload["item_type"] == "subscription"
    session = supabase.storage["one_lat_subscription_sessions"][0]
    assert session["plan_key"] == "test_plan"
    assert session["subscription_plan_id"] == "plan_test"
    assert session["points_per_cycle"] == 100
    assert session["usd_amount"] == 10.0
    assert session["metadata"]["quick_checkout"] is True
