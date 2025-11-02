from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.payouts import (
    AdminPayoutGenerateRequest,
    AdminPayoutListResponse,
    PayoutDashboardResponse,
    PayoutLedgerEntry,
    PayoutSettings,
)
from app.routes import admin_payouts, payouts
from app.services import payouts as payout_service


class StubQuery:
    def __init__(self, supabase: "StubSupabase", table: str):
        self._supabase = supabase
        self._table = table
        self._select: tuple | None = None
        self._filters: list[tuple[str, str, object]] = []
        self._order: tuple[str, bool] | None = None
        self._range: tuple[int, int] | None = None
        self._mutation: str | None = None
        self._payload = None
        self._on_conflict: str | None = None

    def select(self, *args, **kwargs):
        self._select = args
        return self

    def eq(self, key: str, value):
        self._filters.append(("eq", key, value))
        return self

    def in_(self, key: str, values):
        self._filters.append(("in", key, set(values)))
        return self

    def lt(self, key: str, value):
        self._filters.append(("lt", key, value))
        return self

    def order(self, field: str, desc: bool = False):
        self._order = (field, desc)
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def insert(self, data):
        self._mutation = "insert"
        self._payload = data
        return self

    def upsert(self, data, on_conflict: str | None = None):
        self._mutation = "upsert"
        self._payload = data
        self._on_conflict = on_conflict
        return self

    def update(self, data):
        self._mutation = "update"
        self._payload = data
        return self

    def execute(self):
        table = self._supabase.tables.setdefault(self._table, [])

        if self._mutation == "insert":
            payload = self._payload
            inserted = []
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                record = dict(row)
                record.setdefault("id", str(uuid.uuid4()))
                table.append(record)
                inserted.append(record)
            return SimpleNamespace(data=inserted)

        if self._mutation == "upsert":
            payload = self._payload
            if not isinstance(payload, dict):
                raise AssertionError("Upsert expects dict payload in tests")
            key = self._on_conflict or "id"
            match_value = payload.get(key)
            updated = False
            for existing in table:
                if existing.get(key) == match_value and match_value is not None:
                    existing.update(payload)
                    updated = True
                    target = existing
                    break
            if not updated:
                record = dict(payload)
                record.setdefault("id", str(uuid.uuid4()))
                table.append(record)
                target = record
            return SimpleNamespace(data=[target])

        if self._mutation == "update":
            payload = dict(self._payload or {})
            updated_rows = []
            for row in table:
                include = True
                for kind, key, value in self._filters:
                    if kind == "eq" and row.get(key) != value:
                        include = False
                        break
                    if kind == "in" and row.get(key) not in value:
                        include = False
                        break
                if include:
                    row.update(payload)
                    updated_rows.append(row)
            return SimpleNamespace(data=updated_rows)

        return self.execute_select()

    def _apply_filters(self, rows: list[dict]) -> list[dict]:
        results = rows
        for kind, key, value in self._filters:
            if kind == "eq":
                results = [row for row in results if row.get(key) == value]
            elif kind == "in":
                results = [row for row in results if row.get(key) in value]
            elif kind == "lt":
                results = [
                    row
                    for row in results
                    if row.get(key) is not None and str(row.get(key)) < str(value)
                ]
        return results

    def execute_select(self):
        table = list(self._supabase.tables.get(self._table, []))
        rows = self._apply_filters(table)

        if self._order:
            field, desc = self._order
            rows.sort(key=lambda row: row.get(field), reverse=desc)

        if self._range:
            start, end = self._range
            rows = rows[start : end + 1]

        return SimpleNamespace(data=rows)

class StubSupabase:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables: dict[str, list[dict]] = tables or {}

    def table(self, name: str) -> StubQuery:
        return StubQuery(self, name)


def test_generate_payouts_creates_entries(monkeypatch):
    reference_date = datetime(2025, 1, 20, tzinfo=timezone.utc)
    supabase = StubSupabase(
        tables={
            "payment_orders": [
                {
                    "id": "order-1",
                    "seller_id": "seller-1",
                    "user_id": "buyer-1",
                    "amount_jpy": 14500,
                    "currency": "JPY",
                    "metadata": {},
                    "completed_at": "2025-01-05T00:00:00Z",
                    "status": "COMPLETED",
                },
                {
                    "id": "order-2",
                    "seller_id": "seller-1",
                    "user_id": "buyer-2",
                    "amount_usd": 50,
                    "amount_jpy": 7250,
                    "currency": "USD",
                    "metadata": {"description": "NOTE"},
                    "completed_at": "2025-01-07T12:30:00Z",
                    "status": "COMPLETED",
                    "reserve_amount_usd": 2.5,
                },
            ],
            "payout_line_items": [],
            "payout_ledger": [],
            "payout_events": [],
            "users": [
                {"id": "seller-1", "username": "seller", "email": "seller@example.com"},
            ],
            "payout_settings": [
                {"user_id": "seller-1", "usdt_address": "T1234567890", "payout_cycle_days": 10},
            ],
        }
    )

    result = payout_service.generate_payouts(
        AdminPayoutGenerateRequest(reference_date=reference_date, lookback_days=20, fee_percent=5.0),
        actor_id="admin-1",
        supabase=supabase,
    )

    assert result["total_created"] == 1
    ledger_rows = supabase.tables["payout_ledger"]
    assert len(ledger_rows) == 1
    ledger = ledger_rows[0]
    assert ledger["status"] == "ready_to_payout"
    # 14500 JPY ≒ 100 USD, plus 50 USD => 150 USD gross, 5% fee => 142.5 net, reserve 2.5 USD => 140 net
    assert abs(float(ledger["gross_amount_usd"]) - 150.0) < 0.01
    assert abs(float(ledger["net_amount_usd"]) - 140.0) < 0.01
    assert ledger["seller_wallet_snapshot"] == "T1234567890"
    assert ledger["metadata"]["reserve_withheld_usd"] == 2.5

    line_items = supabase.tables["payout_line_items"]
    assert len(line_items) == 2
    assert {item["source_id"] for item in line_items} == {"order-1", "order-2"}

    events = supabase.tables["payout_events"]
    assert any(event.get("event_type") == "generated" for event in events)


def test_payout_dashboard_groups_pending(monkeypatch):
    supabase = StubSupabase(
        tables={
            "payout_settings": [
                {
                    "user_id": "seller-1",
                    "usdt_address": "T123",
                    "payout_cycle_days": 10,
                    "created_at": "2025-01-01T00:00:00Z",
                },
            ],
            "payout_ledger": [
                {
                    "id": "payout-1",
                    "seller_id": "seller-1",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-05T00:00:00Z",
                    "settlement_due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                    "status": "ready_to_payout",
                    "gross_amount_usd": 100,
                    "net_amount_usdt": 95,
                    "currency": "USDT",
                    "created_at": "2025-01-05T00:00:00Z",
                    "updated_at": "2025-01-05T00:00:00Z",
                },
                {
                    "id": "payout-2",
                    "seller_id": "seller-1",
                    "period_start": "2024-12-15T00:00:00Z",
                    "period_end": "2024-12-20T00:00:00Z",
                    "settlement_due_at": "2024-12-30T00:00:00Z",
                    "status": "paid",
                    "gross_amount_usd": 80,
                    "net_amount_usdt": 76,
                    "currency": "USDT",
                    "created_at": "2024-12-20T00:00:00Z",
                    "updated_at": "2024-12-31T00:00:00Z",
                },
            ],
        }
    )

    monkeypatch.setattr(payout_service, "get_supabase", lambda: supabase)

    dashboard = payout_service.get_payout_dashboard("seller-1")
    assert isinstance(dashboard, PayoutDashboardResponse)
    assert dashboard.settings is not None
    assert len(dashboard.pending_records) == 1
    assert len(dashboard.recent_records) == 1
    assert dashboard.pending_net_amount_usdt == 95


def test_payout_routes(monkeypatch):
    app = FastAPI()
    app.include_router(payouts.router, prefix="/api")
    app.include_router(admin_payouts.router, prefix="/api")

    monkeypatch.setattr(payouts, "_get_current_user", lambda _cred: {"id": "seller-1"})
    monkeypatch.setattr(admin_payouts, "require_admin", lambda *_args, **_kwargs: {"id": "admin-1"})
    monkeypatch.setattr(payout_service, "get_payout_dashboard", lambda user_id, supabase=None: PayoutDashboardResponse())
    monkeypatch.setattr(payout_service, "get_payout_settings", lambda user_id, supabase=None: PayoutSettings(user_id=user_id, usdt_address="T123", preferred_network="TRC20", payout_cycle_days=10))
    monkeypatch.setattr(payout_service, "upsert_payout_settings", lambda user_id, payload, actor_id=None, supabase=None: PayoutSettings(user_id=user_id, usdt_address=payload.usdt_address, preferred_network=payload.preferred_network or "TRC20", payout_cycle_days=10))
    monkeypatch.setattr(payout_service, "get_payout_detail", lambda payout_id, supabase=None: PayoutLedgerEntry(
        id=payout_id,
        seller_id="seller-1",
        seller_username="seller",
        seller_email="seller@example.com",
        period_start=datetime.now(timezone.utc),
        period_end=datetime.now(timezone.utc),
        settlement_due_at=datetime.now(timezone.utc),
        payout_cycle_days=10,
        currency="USDT",
        gross_amount_usd=100.0,
        status="ready_to_payout",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        line_items=[],
        events=[],
    ))
    monkeypatch.setattr(payout_service, "list_admin_payouts", lambda *args, **kwargs: AdminPayoutListResponse(total=0, data=[]))
    monkeypatch.setattr(payout_service, "generate_payouts", lambda request, actor_id=None, supabase=None: {"created": [], "total_created": 0})
    monkeypatch.setattr(payout_service, "update_payout_status", lambda payout_id, payload, actor_id=None, supabase=None: payout_service.get_payout_detail(payout_id))
    monkeypatch.setattr(payout_service, "record_admin_transaction", lambda payout_id, payload, actor_id=None, supabase=None: payout_service.get_payout_detail(payout_id))
    monkeypatch.setattr(payout_service, "create_admin_event", lambda payout_id, payload, actor_id=None, supabase=None: {"id": "event-1", "payout_id": payout_id})

    client = TestClient(app)

    assert client.get("/api/payouts/dashboard").status_code == 200
    assert client.get("/api/payouts/settings").status_code == 200
    assert client.put("/api/payouts/settings", json={"usdt_address": "T987"}).status_code == 200
    assert client.get("/api/payouts/ledger/p1").status_code == 200

    assert client.get("/api/admin/payouts").status_code == 200
    assert client.post("/api/admin/payouts/generate", json={"lookback_days": 10}).status_code == 200
    assert client.get("/api/admin/payouts/p1").status_code == 200
    assert client.post("/api/admin/payouts/p1/status", json={"status": "paid"}).status_code == 200
    assert client.post("/api/admin/payouts/p1/transaction", json={"tx_hash": "abc"}).status_code == 200
    assert client.post("/api/admin/payouts/p1/events", json={"event_type": "note"}).status_code == 200


def test_list_risk_orders():
    supabase = StubSupabase(
        tables={
            "payment_orders": [
                {
                    "id": "order-risk-1",
                    "seller_id": "seller-1",
                    "user_id": "buyer-1",
                    "amount_jpy": 20000,
                    "currency": "JPY",
                    "status": "COMPLETED",
                    "clearing_state": "clearing",
                    "risk_level": "medium",
                    "risk_score": 4,
                    "completed_at": "2025-01-10T00:00:00Z",
                    "ready_for_payout_at": "2025-02-01T00:00:00Z",
                    "chargeback_hold_until": "2025-02-01T00:00:00Z",
                    "reserve_amount_usd": 5,
                    "created_at": "2025-01-10T00:00:00Z",
                    "metadata": {"risk_snapshot": {"factors": {"high_amount": True}}},
                },
                {
                    "id": "order-safe-1",
                    "seller_id": "seller-2",
                    "user_id": "buyer-2",
                    "amount_jpy": 8000,
                    "currency": "JPY",
                    "status": "COMPLETED",
                    "clearing_state": "ready",
                    "risk_level": "low",
                    "risk_score": 1,
                    "completed_at": "2025-01-05T00:00:00Z",
                    "ready_for_payout_at": "2025-01-15T00:00:00Z",
                    "created_at": "2025-01-05T00:00:00Z",
                    "metadata": {},
                },
            ],
            "users": [
                {"id": "seller-1", "username": "seller-one", "email": "seller1@example.com"},
                {"id": "buyer-1", "username": "buyer-one", "email": "buyer1@example.com"},
            ],
        }
    )

    result = payout_service.list_risk_orders(limit=10, supabase=supabase)
    assert result.total == 1
    assert len(result.data) == 1
    order = result.data[0]
    assert order.order_id == "order-risk-1"
    assert order.risk_level == "medium"
    assert order.clearing_state == "clearing"
