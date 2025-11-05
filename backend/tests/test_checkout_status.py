import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import products, subscriptions


app = FastAPI()
app.include_router(products.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")


def _override_security() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def setup_module(_: object):
    app.dependency_overrides[products.security] = _override_security
    app.dependency_overrides[subscriptions.security] = _override_security


def teardown_module(_: object):
    app.dependency_overrides.pop(products.security, None)
    app.dependency_overrides.pop(subscriptions.security, None)


class FakeSelectQuery:
    def __init__(self, store: dict[str, list[dict]], table: str):
        self._store = store
        self._table = table
        self._filters: list[tuple[str, str, object]] = []
        self._maybe_single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column: str, value):
        self._filters.append(("eq", column, value))
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def execute(self):
        rows = list(self._store.get(self._table, []))
        for _op, column, value in self._filters:
            rows = [row for row in rows if row.get(column) == value]
        if self._maybe_single:
            result = rows[0] if rows else None
            return SimpleNamespace(data=result)
        return SimpleNamespace(data=rows)


class FakeUpdateQuery:
    def __init__(self, store: dict[str, list[dict]], table: str, payload: dict):
        self._store = store
        self._table = table
        self._payload = payload
        self._filters: list[tuple[str, str, object]] = []

    def eq(self, column: str, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        rows = self._store.get(self._table, [])
        matched = []
        for row in rows:
            if all(row.get(column) == value for column, value in self._filters):
                row.update(self._payload)
                matched.append(row)
        return SimpleNamespace(data=matched)


class FakeTable:
    def __init__(self, store: dict[str, list[dict]], table: str):
        self._store = store
        self._table = table

    def select(self, *_args, **_kwargs):
        return FakeSelectQuery(self._store, self._table)

    def update(self, payload: dict):
        return FakeUpdateQuery(self._store, self._table, payload)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str):
        return FakeTable(self.tables, name)


def test_product_order_status_triggers_notification(monkeypatch):
    fake_store = {
        "payment_orders": [
            {
                "id": "order-id",
                "external_id": "test-product-order-1",
                "user_id": "user-id",
                "item_id": "product-id",
                "status": "COMPLETED",
                "metadata": {"quantity": 2},
                "amount_jpy": 4800,
                "payment_method": "yen",
            }
        ],
        "products": [
            {
                "id": "product-id",
                "title": "オンライン講座セット",
                "seller_id": "seller-id",
                "thanks_lp_id": "lp-id",
                "redirect_url": "https://example.invalid/thank-you",
            }
        ],
        "landing_pages": [
            {
                "id": "lp-id",
                "slug": "thank-you-slug",
            }
        ],
    }

    supabase = FakeSupabase(fake_store)
    monkeypatch.setattr(products, "get_supabase", lambda: supabase)
    monkeypatch.setattr(products, "get_current_user_id", lambda _cred: "user-id")

    notification_calls = {}

    def _fake_send_notification(*_args, **_kwargs):
        notification_calls["called"] = True
        return "msg-1"

    monkeypatch.setattr(products, "send_purchase_notification", _fake_send_notification)

    client = TestClient(app)
    response = client.get("/api/products/orders/status", params={"external_id": "test-product-order-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["notification_sent"] is True
    assert payload["thanks_lp_slug"] == "thank-you-slug"
    assert notification_calls.get("called") is True
    assert fake_store["payment_orders"][0]["metadata"]["purchase_notification_sent"] is True


def test_product_order_status_forbidden(monkeypatch):
    fake_store = {
        "payment_orders": [
            {
                "id": "order-id-2",
                "external_id": "test-product-order-2",
                "user_id": "different-user",
                "item_id": "product-id-2",
                "status": "PENDING",
                "metadata": {},
            }
        ],
        "products": [],
    }

    supabase = FakeSupabase(fake_store)
    monkeypatch.setattr(products, "get_supabase", lambda: supabase)
    monkeypatch.setattr(products, "get_current_user_id", lambda _cred: "user-id")

    client = TestClient(app)
    response = client.get("/api/products/orders/status", params={"external_id": "test-product-order-2"})

    assert response.status_code == 403


def test_subscription_session_status_resends_notification(monkeypatch):
    fake_store = {
        "one_lat_subscription_sessions": [
            {
                "id": "session-id",
                "external_id": "test-subscription-session",
                "user_id": "user-id",
                "plan_key": "demo_plan",
                "subscription_plan_id": "demo-plan-id",
                "status": "RECURRENT_PAYMENT.ACTIVE",
                "last_event_type": "RECURRENT_PAYMENT.ACTIVE",
                "last_event_at": "2025-01-01T00:00:00Z",
                "metadata": {
                    "billing_method": "salon_yen",
                    "price_jpy": 5500,
                    "salon_id": "salon-id",
                },
                "seller_id": "seller-id",
                "seller_username": "creator",
                "salon_id": "salon-id",
            }
        ],
        "user_subscriptions": [
            {
                "id": "subscription-id",
                "external_id": "test-subscription-session",
                "status": "ACTIVE",
                "last_event_type": "RECURRENT_PAYMENT.ACTIVE",
                "last_event_at": "2025-01-01T00:00:00Z",
                "metadata": {},
                "recurrent_payment_id": "recurrent-id",
                "seller_id": "seller-id",
                "seller_username": "creator",
                "salon_id": "salon-id",
            }
        ],
        "salons": [
            {
                "id": "salon-id",
                "title": "クリエイターズラボ",
                "owner_id": "seller-id",
            }
        ],
        "salon_memberships": [
            {
                "id": "membership-id",
                "salon_id": "salon-id",
                "user_id": "user-id",
                "status": "ACTIVE",
            }
        ],
    }

    supabase = FakeSupabase(fake_store)
    monkeypatch.setattr(subscriptions, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(subscriptions, "_get_current_user_id", lambda _cred: "user-id")

    monkeypatch.setattr(
        subscriptions,
        "get_subscription_plan",
        lambda _key: SimpleNamespace(
            key="demo_plan",
            label="980pt / 月",
            points=980,
            usd_amount=6.76,
            subscription_plan_id="demo-plan-id",
        ),
    )
    monkeypatch.setattr(
        subscriptions,
        "get_subscription_plan_by_id",
        lambda _id: SimpleNamespace(
            key="demo_plan",
            label="980pt / 月",
            points=980,
            usd_amount=6.76,
            subscription_plan_id="demo-plan-id",
        ),
    )

    notification_calls = {}

    def _fake_send_notification(*_args, **_kwargs):
        notification_calls["called"] = True
        return "msg-sub-1"

    monkeypatch.setattr(subscriptions, "send_purchase_notification", _fake_send_notification)

    client = TestClient(app)
    response = client.get("/api/subscriptions/session-status", params={"external_id": "test-subscription-session"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_sent"] is True
    assert payload["is_completed"] is True
    assert payload.get("salon", {}).get("id") == "salon-id"
    assert notification_calls.get("called") is True
    assert fake_store["one_lat_subscription_sessions"][0]["metadata"]["purchase_notification_sent"] is True
    assert fake_store["user_subscriptions"][0]["metadata"]["purchase_notification_id"] == "msg-sub-1"
