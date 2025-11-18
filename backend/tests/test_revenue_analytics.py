from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import admin


class RevenueStubQuery:
    def __init__(self, supabase: "RevenueStubSupabase", table: str) -> None:
        self._supabase = supabase
        self._table = table
        self._filters: Dict[str, Any] = {}
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None

    def select(self, *_columns, **_kwargs):
        return self

    def eq(self, column: str, value: Any):
        self._filters[column] = value
        return self

    def order(self, column: str, desc: bool = False):
        self._order = (column, desc)
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def execute(self):
        rows = [dict(row) for row in self._supabase.tables.get(self._table, [])]
        for column, expected in self._filters.items():
            rows = [row for row in rows if row.get(column) == expected]

        if self._order:
            field, desc = self._order
            rows.sort(key=lambda row: row.get(field) or "", reverse=desc)

        if self._limit is not None:
            rows = rows[: self._limit]

        return SimpleNamespace(data=rows)


class RevenueStubSupabase:
    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self.tables = tables

    def table(self, name: str) -> RevenueStubQuery:
        return RevenueStubQuery(self, name)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        base = datetime(2025, 11, 17, 0, 0, 0, tzinfo=timezone.utc)
        if tz:
            return base.astimezone(tz)
        return base


@pytest.mark.asyncio
async def test_get_revenue_analytics(monkeypatch):
    tables = {
        "payment_orders": [
            {
                "id": "o1",
                "amount_jpy": 10000,
                "status": "COMPLETED",
                "created_at": "2025-11-14T09:00:00+00:00",
                "completed_at": "2025-11-14T09:05:00+00:00",
                "ready_for_payout_at": "2025-11-16T09:05:00+00:00",
                "reserve_released_at": None,
                "clearing_state": "pending",
            },
            {
                "id": "o2",
                "amount_jpy": 5000,
                "status": "COMPLETED",
                "created_at": "2025-11-10T05:00:00+00:00",
                "completed_at": "2025-11-10T05:10:00+00:00",
                "ready_for_payout_at": "2025-11-12T05:10:00+00:00",
                "reserve_released_at": "2025-11-13T05:10:00+00:00",
                "clearing_state": "released",
            },
            {
                "id": "o3",
                "amount_jpy": 3000,
                "status": "COMPLEED",  # will be excluded because of status typo
                "created_at": "2025-10-20T02:00:00+00:00",
                "completed_at": "2025-10-20T02:15:00+00:00",
                "ready_for_payout_at": "2025-10-30T02:15:00+00:00",
                "reserve_released_at": None,
                "clearing_state": "clearing",
            },
            {
                "id": "o3b",
                "amount_jpy": 3000,
                "status": "COMPLETED",
                "created_at": "2025-10-20T02:00:00+00:00",
                "completed_at": "2025-10-20T02:15:00+00:00",
                "ready_for_payout_at": "2025-10-30T02:15:00+00:00",
                "reserve_released_at": None,
                "clearing_state": "clearing",
            },
            {
                "id": "o4",
                "amount_jpy": 0,
                "status": "COMPLETED",
                "created_at": "2025-11-12T02:00:00+00:00",
                "completed_at": "2025-11-12T02:10:00+00:00",
                "ready_for_payout_at": "2025-11-14T02:10:00+00:00",
                "reserve_released_at": None,
                "clearing_state": "pending",
            },
            {
                "id": "o5",
                "amount_jpy": 4000,
                "status": "COMPLETED",
                "created_at": "2025-08-01T03:00:00+00:00",
                "completed_at": "2025-08-01T03:20:00+00:00",
                "ready_for_payout_at": "2025-08-05T03:20:00+00:00",
                "reserve_released_at": "2025-08-06T03:20:00+00:00",
                "clearing_state": "released",
            },
            {
                "id": "o6",
                "amount_jpy": 2500,
                "status": "COMPLETED",
                "created_at": "2025-11-15T04:00:00+00:00",
                "completed_at": "2025-11-15T04:05:00+00:00",
                "ready_for_payout_at": "2025-11-19T04:05:00+00:00",
                "reserve_released_at": None,
                "clearing_state": "pending",
            },
        ],
        "point_transactions": [
            {
                "transaction_type": "purchase",
                "amount": 500,
                "created_at": "2025-11-16T00:00:00+00:00",
            },
            {
                "transaction_type": "admin_grant",
                "amount": 300,
                "created_at": "2025-11-12T00:00:00+00:00",
            },
            {
                "transaction_type": "manual_adjust",
                "amount": 200,
                "created_at": "2025-10-25T00:00:00+00:00",
            },
            {
                "transaction_type": "bonus",
                "amount": 150,
                "created_at": "2025-11-05T00:00:00+00:00",
            },
            {
                "transaction_type": "note_share_reward",
                "amount": 120,
                "created_at": "2025-11-14T00:00:00+00:00",
            },
            {
                "transaction_type": "product_purchase",
                "amount": -400,
                "created_at": "2025-11-09T00:00:00+00:00",
            },
            {
                "transaction_type": "other_event",
                "amount": 50,
                "created_at": "2025-09-01T00:00:00+00:00",
            },
        ],
    }

    stub = RevenueStubSupabase(tables)
    monkeypatch.setattr(admin, "get_supabase", lambda: stub)
    monkeypatch.setattr(admin, "_get_effective_exchange_rate_decimal", lambda: Decimal("150"))
    monkeypatch.setattr(admin, "datetime", _FixedDatetime)

    result = await admin.get_revenue_analytics(limit_days=120, admin={"id": "admin-user"})

    assert result.summary.total_orders == 6
    assert result.summary.total_revenue_jpy == pytest.approx(25000.0)
    assert result.summary.average_order_value_jpy == pytest.approx(4166.6667, rel=1e-4)
    assert result.summary.last_seven_days_jpy == pytest.approx(18000.0)
    assert result.summary.last_thirty_days_jpy == pytest.approx(21000.0)
    assert result.summary.total_revenue_usdt == pytest.approx(166.6667, rel=1e-4)

    ready_bucket = next(bucket for bucket in result.settlements.buckets if bucket.key == "ready")
    assert ready_bucket.order_count == 2
    assert ready_bucket.amount_jpy == pytest.approx(13000.0)
    assert ready_bucket.average_wait_days == pytest.approx(6.0)

    released_bucket = next(bucket for bucket in result.settlements.buckets if bucket.key == "released")
    assert released_bucket.order_count == 2
    assert released_bucket.amount_jpy == pytest.approx(9000.0)
    assert released_bucket.average_wait_days == pytest.approx(3.0)

    pending_bucket = next(bucket for bucket in result.settlements.buckets if bucket.key == "pending")
    assert pending_bucket.order_count == 1
    assert pending_bucket.amount_jpy == pytest.approx(2500.0)

    assert result.point_net.total_granted == 770
    assert result.point_net.total_spent == 400
    assert result.point_net.net_points == 370

    categories = {item.category: item.total_points for item in result.point_categories}
    assert categories["admin_grant"] == 500  # 300 + 200
    assert categories["note_share_reward"] == 120
    assert categories["bonus"] == 150
    assert categories["spent"] == -400

    series_dates = {entry.date for entry in result.point_series}
    assert "2025-11-16" in series_dates
    assert "2025-11-12" in series_dates
    assert "2025-11-09" in series_dates
