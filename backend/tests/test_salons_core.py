from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

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
        self._limit: Optional[int] = None
        self._updates: Optional[Dict[str, Any]] = None
        self._insert_payload: Optional[Any] = None
        self._order: Optional[tuple[str, bool]] = None
        self._range: Optional[tuple[int, int]] = None

    def select(self, *_args, **kwargs):
        self._operation = "select"
        self._count_mode = kwargs.get("count")
        self._limit = None
        self._order = None
        self._range = None
        return self

    def delete(self):
        self._operation = "delete"
        return self

    def insert(self, payload: Any):
        self._operation = "insert"
        self._insert_payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._updates = payload
        return self

    def eq(self, field: str, value: Any):
        self._filters.append((field, value))
        return self

    def ilike(self, field: str, value: str):
        self._filters.append((field, (value or "").lower(), "ilike"))
        return self

    def or_(self, expression: str):
        clauses = []
        for clause in expression.split(","):
            parts = clause.split(".", 2)
            if len(parts) == 3:
                clauses.append((parts[0], parts[1], parts[2]))
        self._filters.append(("__or__", clauses))
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def order(self, field: str, desc: bool = False):
        self._order = (field, desc)
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self.supabase.tables[self.name]
        def _matches(row: Dict[str, Any]) -> bool:
            for condition in self._filters:
                field = condition[0]
                if field == "__or__":
                    clauses = condition[1]
                    if not any(
                        (clause_field == "email" and clause_op == "ilike" and (row.get(clause_field) or "").lower() == clause_value.lower())
                        or (row.get(clause_field) == clause_value)
                        for clause_field, clause_op, clause_value in clauses
                    ):
                        return False
                    continue
                if len(condition) == 3 and condition[2] == "ilike":
                    if (row.get(field) or "").lower() != condition[1]:
                        return False
                else:
                    if row.get(field) != condition[1]:
                        return False
            return True

        matches = [row for row in rows if _matches(row)] if self._filters else list(rows)

        if self._order:
            field, desc = self._order
            matches.sort(key=lambda row: row.get(field), reverse=desc)

        if self._range:
            start, end = self._range
            matches = matches[start:end + 1]

        if self._operation == "delete":
            self.supabase.tables[self.name] = [row for row in rows if row not in matches]
            return SimpleNamespace(data=matches)

        if self._operation == "insert":
            payloads = self._insert_payload if isinstance(self._insert_payload, list) else [self._insert_payload]
            inserted: List[Dict[str, Any]] = []
            for payload in payloads:
                new_row = payload.copy()
                new_row.setdefault("id", f"{self.name}-{len(self.supabase.tables[self.name]) + len(inserted) + 1}")
                self.supabase.tables[self.name].append(new_row)
                inserted.append(new_row)
            return SimpleNamespace(data=inserted)

        if self._operation == "update":
            updated: List[Dict[str, Any]] = []
            for row in rows:
                if _matches(row):
                    row.update(self._updates or {})
                    updated.append(row.copy())
            return SimpleNamespace(data=updated)

        response = SimpleNamespace(data=matches)
        if self._count_mode == "exact":
            response.count = len(matches)
        if self._limit is not None:
            response.data = matches[: self._limit]
        return response


def _setup_app(stub: StubSupabase, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(salons.router, prefix="/api")

    def fake_current_user(_credentials):
        return {"id": "seller-1", "user_type": "seller"}

    def fake_get_salon(_salon_id: str, owner_id: str):
        for record in stub.tables.get("salons", []):
            if record.get("id") == _salon_id and record.get("owner_id") == owner_id:
                return record
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


def test_manual_member_invite_creates_membership(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1", "subscription_plan_id": "plan-1"}],
            "salon_memberships": [],
            "users": [{"id": "user-1", "email": "friend@example.com", "username": "friend"}],
            "user_subscriptions": [],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.post(
        "/api/salons/salon-1/members/manual",
        headers={"Authorization": "Bearer token"},
        json={"email": "friend@example.com", "memo": "bank transfer", "status": "ACTIVE"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["user_id"] == "user-1"
    assert payload["status"] == "ACTIVE"
    assert payload["metadata"]["source"] == "manual_invite"
    assert stub.tables["salon_memberships"], "membership created"
    assert stub.tables["user_subscriptions"], "subscription created"


def test_manual_member_invite_rejects_existing_active_member(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1"}],
            "salon_memberships": [
                {
                    "id": "membership-1",
                    "salon_id": "salon-1",
                    "user_id": "user-1",
                    "status": "ACTIVE",
                    "metadata": {"source": "one_lat"},
                }
            ],
            "users": [{"id": "user-1", "email": "friend@example.com", "username": "friend"}],
            "user_subscriptions": [],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.post(
        "/api/salons/salon-1/members/manual",
        headers={"Authorization": "Bearer token"},
        json={"email": "friend@example.com"},
    )

    assert response.status_code == 400


def test_manual_member_invite_missing_user(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1"}],
            "salon_memberships": [],
            "users": [],
            "user_subscriptions": [],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.post(
        "/api/salons/salon-1/members/manual",
        headers={"Authorization": "Bearer token"},
        json={"email": "missing@example.com"},
    )

    assert response.status_code == 404


def test_list_salon_members_includes_user_fields(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1"}],
            "salon_memberships": [
                {
                    "id": "membership-1",
                    "salon_id": "salon-1",
                    "user_id": "user-1",
                    "status": "ACTIVE",
                    "joined_at": "2025-12-01T00:00:00Z",
                    "metadata": {
                        "source": "manual_invite",
                        "manual_invite": {"expires_at": "2025-12-31T00:00:00Z"},
                    },
                    "user": {
                        "email": "friend@example.com",
                        "username": "friend",
                        "display_name": "Friend",
                    },
                }
            ],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.get(
        "/api/salons/salon-1/members",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    row = payload["data"][0]
    assert row["user_email"] == "friend@example.com"
    assert row["user_username"] == "friend"
    assert row["manual_expires_at"].startswith("2025-12-31")


def test_update_manual_member_allows_status_and_expiry(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1", "subscription_plan_id": "plan-1"}],
            "salon_memberships": [
                {
                    "id": "membership-1",
                    "salon_id": "salon-1",
                    "user_id": "user-1",
                    "status": "ACTIVE",
                    "joined_at": "2025-11-01T00:00:00Z",
                    "metadata": {"source": "manual_invite", "manual_invite": {"memo": "wire"}},
                    "user": {
                        "email": "friend@example.com",
                        "username": "friend",
                        "display_name": "Friend",
                    },
                }
            ],
            "user_subscriptions": [],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.patch(
        "/api/salons/salon-1/members/membership-1",
        headers={"Authorization": "Bearer token"},
        json={
            "status": "CANCELED",
            "memo": "refund",
            "expires_at": "2025-12-31T00:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "CANCELED"
    assert payload["manual_expires_at"].startswith("2025-12-31")
    assert payload["user_email"] == "friend@example.com"
    assert stub.tables["salon_memberships"][0]["status"] == "CANCELED"


def test_update_manual_member_rejects_non_manual(monkeypatch):
    stub = StubSupabase(
        tables={
            "salons": [{"id": "salon-1", "owner_id": "seller-1"}],
            "salon_memberships": [
                {
                    "id": "membership-1",
                    "salon_id": "salon-1",
                    "user_id": "user-1",
                    "status": "ACTIVE",
                    "joined_at": "2025-11-01T00:00:00Z",
                    "metadata": {"source": "one_lat"},
                }
            ],
        }
    )
    client = _setup_app(stub, monkeypatch)

    response = client.patch(
        "/api/salons/salon-1/members/membership-1",
        headers={"Authorization": "Bearer token"},
        json={"status": "CANCELED"},
    )

    assert response.status_code == 400
