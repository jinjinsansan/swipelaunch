import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import admin


class _Response:
    def __init__(self, data=None, count: Optional[int] = None):
        self.data = data
        self.count = count


class FakeSupabase:
    def __init__(self, initial_tables: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        if initial_tables:
            for name, rows in initial_tables.items():
                self.tables[name] = [deepcopy(row) for row in rows]

    def table(self, name: str):
        if name not in self.tables:
            self.tables[name] = []
        return _Table(self, name)


class _Table:
    def __init__(self, client: FakeSupabase, name: str) -> None:
        self.client = client
        self.name = name
        self._filters: List[tuple[str, str, Any]] = []
        self._order: List[tuple[str, bool]] = []
        self._range: Optional[tuple[int, int]] = None
        self._limit: Optional[int] = None
        self._operation: str = "select"
        self._payload: Any = None
        self._count_mode: Optional[str] = None
        self._single: bool = False
        self._maybe_single: bool = False

    @property
    def _table(self) -> List[Dict[str, Any]]:
        return self.client.tables[self.name]

    def _matching_rows(self) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for row in self._table:
            keep = True
            for op, field, value in self._filters:
                current = row.get(field)
                if op == "eq" and current != value:
                    keep = False
                    break
            if keep:
                matches.append(row)
        return matches

    def select(self, *_: Any, **kwargs: Any):
        self._operation = "select"
        self._count_mode = kwargs.get("count")
        return self

    def eq(self, field: str, value: Any):
        self._filters.append(("eq", field, value))
        return self

    def order(self, field: str, desc: bool = False):
        self._order.append((field, desc))
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def insert(self, payload: Dict[str, Any]):
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        return self

    def execute(self):
        if self._operation == "insert":
            record = deepcopy(self._payload)
            now = datetime.now(timezone.utc).isoformat()
            record.setdefault("id", f"{self.name}-{len(self._table) + 1}")
            record.setdefault("created_at", now)
            record.setdefault("updated_at", now)
            self._table.append(record)
            return _Response(data=[deepcopy(record)])

        if self._operation == "update":
            updated: List[Dict[str, Any]] = []
            for row in self._matching_rows():
                row.update(self._payload)
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
                updated.append(deepcopy(row))
            return _Response(data=updated)

        rows = [deepcopy(row) for row in self._matching_rows()]

        for field, desc in reversed(self._order):
            rows.sort(key=lambda item: item.get(field), reverse=desc)

        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]

        if self._limit is not None:
            rows = rows[: self._limit]

        if self._single or self._maybe_single:
            if rows:
                return _Response(data=rows[0])
            return _Response(data=None)

        count = len(self._matching_rows()) if self._count_mode == "exact" else None
        return _Response(data=rows, count=count)


def _build_client(monkeypatch, tables: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None):
    fake = FakeSupabase(tables)
    app = FastAPI()
    app.include_router(admin.router, prefix="/api")
    app.dependency_overrides[admin.require_admin] = lambda: {
        "id": "admin-1",
        "email": "goldbenchan@gmail.com",
    }
    monkeypatch.setattr(admin, "get_supabase", lambda: fake)
    return TestClient(app), fake


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_list_maintenance_modes_filters_scope_and_status(monkeypatch):
    tables = {
        "maintenance_modes": [
            {
                "id": "mode-1",
                "scope": "global",
                "status": "scheduled",
                "title": "全体メンテ",
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "mode-2",
                "scope": "lp",
                "status": "active",
                "title": "LP緊急",
                "created_at": "2025-01-02T00:00:00+00:00",
                "updated_at": "2025-01-02T00:00:00+00:00",
            },
        ]
    }
    client, _ = _build_client(monkeypatch, tables)

    response = client.get("/api/admin/maintenance/modes", headers=_auth_headers(), params={"scope": "lp"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == "mode-2"

    response = client.get(
        "/api/admin/maintenance/modes", headers=_auth_headers(), params={"status": "scheduled"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "scheduled"


def test_create_maintenance_mode_records_event(monkeypatch):
    tables = {"maintenance_modes": [], "moderation_events": []}
    client, fake = _build_client(monkeypatch, tables)

    payload = {
        "scope": "ai",
        "title": "AI推論停止",
        "message": "GPUクラスタ再起動のため",
        "planned_start": "2025-02-01T10:00:00+00:00",
        "planned_end": "2025-02-01T12:00:00+00:00",
    }
    response = client.post("/api/admin/maintenance/modes", json=payload, headers=_auth_headers())
    assert response.status_code == 201
    body = response.json()
    assert body["scope"] == "ai"
    assert body["status"] == "scheduled"
    assert body["title"] == "AI推論停止"

    assert len(fake.tables["maintenance_modes"]) == 1
    stored = fake.tables["maintenance_modes"][0]
    assert stored["scope"] == "ai"
    assert stored["status"] == "scheduled"
    assert stored["planned_start"] == "2025-02-01T10:00:00+00:00"
    assert len(fake.tables["moderation_events"]) == 1
    assert fake.tables["moderation_events"][0]["action"] == "maintenance_mode_create"


def test_update_maintenance_mode_status_sets_activation(monkeypatch):
    tables = {
        "maintenance_modes": [
            {
                "id": "mode-9",
                "scope": "payments",
                "status": "scheduled",
                "title": "決済点検",
                "message": "カード決済プロバイダーのバージョンアップ",
                "planned_start": "2025-03-01T02:00:00+00:00",
                "created_at": "2025-02-20T00:00:00+00:00",
                "updated_at": "2025-02-20T00:00:00+00:00",
                "activated_at": None,
                "deactivated_at": None,
            }
        ],
        "moderation_events": [],
    }
    client, fake = _build_client(monkeypatch, tables)
    monkeypatch.setattr(admin, "now_utc_iso", lambda: "2025-03-01T02:00:00+00:00")

    response = client.post(
        "/api/admin/maintenance/modes/mode-9/status",
        json={"status": "active"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["activated_at"] == "2025-03-01T02:00:00+00:00"

    stored = fake.tables["maintenance_modes"][0]
    assert stored["status"] == "active"
    assert stored["activated_at"] == "2025-03-01T02:00:00+00:00"
    assert len(fake.tables["moderation_events"]) == 1
    assert fake.tables["moderation_events"][0]["action"] == "maintenance_mode_active"


def test_maintenance_overview_groups_status(monkeypatch):
    tables = {
        "maintenance_modes": [
            {
                "id": "mode-active",
                "scope": "global",
                "status": "active",
                "title": "全体メンテ",
                "planned_start": "2025-04-01T01:00:00+00:00",
            },
            {
                "id": "mode-scheduled",
                "scope": "lp",
                "status": "scheduled",
                "title": "LP更新",
                "planned_start": "2025-04-05T04:00:00+00:00",
            },
            {
                "id": "mode-completed",
                "scope": "ai",
                "status": "completed",
                "title": "AI完了",
                "planned_start": "2025-03-20T04:00:00+00:00",
            },
        ]
    }
    client, _ = _build_client(monkeypatch, tables)

    response = client.get("/api/admin/maintenance/overview", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body["active"]) == 1
    assert body["active"][0]["id"] == "mode-active"
    assert len(body["scheduled"]) == 1
    assert body["scheduled"][0]["id"] == "mode-scheduled"
    assert len(body["history"]) == 1
    assert body["history"][0]["id"] == "mode-completed"


def test_system_status_checks_create_and_list(monkeypatch):
    tables = {
        "system_status_checks": [
            {
                "id": "chk-1",
                "component": "API",
                "status": "healthy",
                "message": "正常",
                "checked_at": "2025-04-01T00:00:00+00:00",
            },
            {
                "id": "chk-2",
                "component": "Payments",
                "status": "degraded",
                "message": "遅延",
                "checked_at": "2025-04-01T01:00:00+00:00",
            },
        ]
    }
    client, fake = _build_client(monkeypatch, tables)
    monkeypatch.setattr(admin, "now_utc_iso", lambda: "2025-04-01T02:00:00+00:00")

    list_response = client.get(
        "/api/admin/maintenance/status-checks",
        headers=_auth_headers(),
        params={"limit": 1},
    )
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1

    create_payload = {
        "component": "Payments",
        "status": "healthy",
        "response_time_ms": 120,
        "message": "復旧しました",
    }
    create_response = client.post(
        "/api/admin/maintenance/status-checks",
        json=create_payload,
        headers=_auth_headers(),
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["component"] == "Payments"
    assert created["status"] == "healthy"

    assert len(fake.tables["system_status_checks"]) == 3
