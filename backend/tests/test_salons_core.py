from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import salons


class StubSupabase:
    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self.tables = {name: list(rows) for name, rows in tables.items()}

    def table(self, name: str):
        if name not in self.tables:
            self.tables[name] = []
        return StubTable(self, name)


class StubTable:
    def __init__(self, supabase: StubSupabase, name: str):
        self.supabase = supabase
        self.name = name
        self._filters: List[tuple[str, Any]] = []
        self._operation = "select"
        self._count_mode: str | None = None

    def select(self, *_args, **kwargs):
        self._operation = "select"
        self._count_mode = kwargs.get("count")
        return self

    def delete(self):
        self._operation = "delete"
        return self

    def eq(self, field: str, value: Any):
        self._filters.append((field, value))
        return self

    def execute(self):
        rows = self.supabase.tables[self.name]
        matches = [row for row in rows if all(row.get(field) == value for field, value in self._filters)]
        if self._operation == "delete":
            self.supabase.tables[self.name] = [row for row in rows if row not in matches]
            return SimpleNamespace(data=matches)

        response = SimpleNamespace(data=matches)
        if self._count_mode == "exact":
            response.count = len(matches)
        return response


def _setup_app(stub: StubSupabase, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(salons.router, prefix="/api")

    def fake_current_user(_credentials):
        return {"id": "seller-1", "user_type": "seller"}

    def fake_get_salon(_salon_id: str, owner_id: str):
        return {"id": _salon_id, "owner_id": owner_id}

    monkeypatch.setattr(salons, "get_supabase_client", lambda: stub)
    monkeypatch.setattr(salons, "_get_current_user", fake_current_user)
    monkeypatch.setattr(salons, "_get_salon_owned_by_user", fake_get_salon)

    return TestClient(app)


def test_delete_salon_success(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1"}],
            "salon_memberships": [],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.delete("/api/salons/salon-1", headers={"Authorization": "Bearer token"})

    assert response.status_code == 204
    assert stub.tables["salons"] == []


def test_delete_salon_rejects_when_members_exist(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1"}],
            "salon_memberships": [{"id": "membership-1", "salon_id": "salon-1"}],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.delete("/api/salons/salon-1", headers={"Authorization": "Bearer token"})

    assert response.status_code == 400
    assert stub.tables["salons"] == [{"id": "salon-1", "owner_id": "seller-1"}]
