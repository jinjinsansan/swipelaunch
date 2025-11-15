from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import admin


class StatsStubQuery:
    def __init__(self, supabase: "StatsStubSupabase", table: str) -> None:
        self._supabase = supabase
        self._table = table
        self._filters: List[tuple[str, str, Any]] = []
        self._count_requested = False

    def select(self, *_columns, **kwargs):
        if kwargs.get("count"):
            self._count_requested = True
        return self

    def eq(self, column: str, value: Any):
        self._filters.append(("eq", column, value))
        return self

    def neq(self, column: str, value: Any):
        self._filters.append(("neq", column, value))
        return self

    def gte(self, column: str, value: Any):
        self._filters.append(("gte", column, value))
        return self

    def in_(self, column: str, values: List[Any]):
        self._filters.append(("in", column, list(values)))
        return self

    def execute(self):
        rows = [dict(row) for row in self._supabase.tables.get(self._table, [])]

        def matches(row: Dict[str, Any]) -> bool:
            for op, column, value in self._filters:
                cell = row.get(column)
                if op == "eq" and cell != value:
                    return False
                if op == "neq" and cell == value:
                    return False
                if op == "gte" and (cell is None or cell < value):
                    return False
                if op == "in" and cell not in value:
                    return False
            return True

        filtered = [row for row in rows if matches(row)]
        result = SimpleNamespace(data=filtered)
        if self._count_requested:
            result.count = len(filtered)
        return result


class StatsStubSupabase:
    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self.tables = tables

    def table(self, name: str) -> StatsStubQuery:
        return StatsStubQuery(self, name)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        base = datetime(2025, 11, 15, 15, 0, 0, tzinfo=timezone.utc)
        if tz:
            return base.astimezone(tz)
        return base


@pytest.mark.asyncio
async def test_get_admin_user_stats(monkeypatch):
    tables: Dict[str, List[Dict[str, Any]]] = {
        "users": [
            {
                "id": "u1",
                "email": "seller@example.com",
                "user_type": "seller",
                "created_at": "2025-09-20T00:00:00+00:00",
                "last_login_at": "2025-11-15T14:50:00+00:00",
                "point_balance": 20000,
                "is_blocked": False,
            },
            {
                "id": "u2",
                "email": "buyer1@example.com",
                "user_type": "buyer",
                "created_at": "2025-11-01T00:00:00+00:00",
                "last_login_at": "2025-11-15T13:00:00+00:00",
                "point_balance": 300,
                "is_blocked": False,
            },
            {
                "id": "u3",
                "email": "buyer2@example.com",
                "user_type": "buyer",
                "created_at": "2025-08-01T00:00:00+00:00",
                "last_login_at": "2025-10-01T00:00:00+00:00",
                "point_balance": 1200,
                "is_blocked": True,
            },
            {
                "id": "u4",
                "email": "creator2@example.com",
                "user_type": "seller",
                "created_at": "2025-10-28T00:00:00+00:00",
                "last_login_at": "2025-11-15T14:10:00+00:00",
                "point_balance": 8000,
                "is_blocked": False,
            },
            {
                "id": "u-ex",
                "email": "factorybot@example.com",
                "user_type": "buyer",
                "created_at": "2025-11-10T00:00:00+00:00",
                "last_login_at": "2025-11-15T14:58:00+00:00",
                "point_balance": 500,
                "is_blocked": False,
            },
        ],
        "line_connections": [
            {"user_id": "u1"},
            {"user_id": "u2"},
            {"user_id": "u-ex"},
        ],
    }

    stub = StatsStubSupabase(tables)
    monkeypatch.setattr(admin, "get_supabase", lambda: stub)
    monkeypatch.setattr(admin, "datetime", _FixedDatetime)

    stats = await admin.get_admin_user_stats(admin={"id": "admin-user"})

    assert stats.total_users == 4
    assert stats.new_users_30d == 2
    assert stats.active_users_15m == 1
    assert stats.line_linked_users == 2
    assert stats.seller_count == 2
    assert stats.buyer_count == 2
    assert stats.blocked_users == 1
    assert stats.high_value_users == 1
