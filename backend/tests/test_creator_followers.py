import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import creator_followers


app = FastAPI()
app.include_router(creator_followers.router, prefix="/api")


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def setup_module(_: object):
    app.dependency_overrides[creator_followers.security] = _override_security


def teardown_module(_: object):
    app.dependency_overrides.pop(creator_followers.security, None)


class FakeQuery:
    def __init__(self, parent: "FakeSupabase", table: str):
        self.parent = parent
        self.table = table
        self.operation: Optional[str] = None
        self.payload: Optional[Any] = None
        self.filters: List[tuple[str, str, Any]] = []
        self.expect_single: bool = False
        self.count_requested: bool = False
        self.limit_value: Optional[int] = None

    def select(self, _columns: str, *, count: Optional[str] = None):
        self.operation = "select"
        self.count_requested = count == "exact"
        return self

    def maybe_single(self):
        self.expect_single = True
        return self

    def single(self):
        self.expect_single = True
        return self

    def upsert(self, payload, on_conflict: Optional[str] = None):
        self.operation = "upsert"
        self.payload = {"data": dict(payload), "conflict": on_conflict}
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = dict(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column: str, value: Any):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: List[Any]):
        self.filters.append(("in", column, list(values)))
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def _apply_filters(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for op, column, value in self.filters:
            if op == "eq":
                rows = [row for row in rows if row.get(column) == value]
            elif op == "in":
                values = set(value or [])
                rows = [row for row in rows if row.get(column) in values]
        return rows

    def execute(self):  # type: ignore[override]
        rows = [dict(row) for row in self.parent.storage.get(self.table, [])]
        rows = self._apply_filters(rows)

        if self.operation == "select":
            if self.limit_value is not None:
                rows = rows[: self.limit_value]
            result = SimpleNamespace(data=rows)
            if self.count_requested:
                result.count = len(rows)
            if self.expect_single:
                result.data = rows[0] if rows else None
            return result

        if self.operation == "upsert":
            payload = dict(self.payload["data"])
            conflict = self.payload.get("conflict")
            storage = self.parent.storage.setdefault(self.table, [])
            updated = None
            if conflict:
                keys = [column.strip() for column in conflict.split(",")]
                for index, row in enumerate(storage):
                    if all(row.get(key) == payload.get(key) for key in keys):
                        updated = {**row, **payload}
                        storage[index] = updated
                        break
            if updated is None:
                updated = payload
                storage.append(updated)
            return SimpleNamespace(data=[dict(updated)])

        if self.operation == "update":
            storage = self.parent.storage.get(self.table, [])
            updated_rows = []
            for index, row in enumerate(storage):
                if row in rows:
                    updated = {**row, **self.payload}
                    storage[index] = updated
                    updated_rows.append(dict(updated))
            self.parent.storage[self.table] = storage
            return SimpleNamespace(data=updated_rows)

        if self.operation == "delete":
            storage = self.parent.storage.get(self.table, [])
            remaining = [row for row in storage if row not in rows]
            self.parent.storage[self.table] = remaining
            return SimpleNamespace(data=None)

        raise AssertionError("Unsupported operation")


class FakeSupabase:
    def __init__(self, users: List[Dict[str, Any]]):
        self.storage: Dict[str, List[Dict[str, Any]]] = {
            "users": [dict(user) for user in users],
            "creator_followers": [],
        }

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def test_follow_flow(monkeypatch):
    supabase = FakeSupabase([
        {"id": "creator-1", "username": "creator"},
        {"id": "follower-1", "username": "reader"},
    ])
    monkeypatch.setattr(creator_followers, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(creator_followers, "decode_access_token", lambda _token: {"sub": "follower-1"})

    client = TestClient(app)

    # Initially not following
    response = client.get("/api/creators/creator-1/follow")
    assert response.status_code == 200
    data = response.json()
    assert data["following"] is False
    assert data["follower_count"] == 0

    # Follow creator
    response = client.post("/api/creators/creator-1/follow", json={"notify_email": True})
    assert response.status_code == 200
    data = response.json()
    assert data["following"] is True
    assert data["notify_email"] is True
    assert data["follower_count"] == 1

    # Update notification preference
    response = client.patch("/api/creators/creator-1/follow", json={"notify_email": False})
    assert response.status_code == 200
    data = response.json()
    assert data["notify_email"] is False

    # Unfollow
    response = client.delete("/api/creators/creator-1/follow")
    assert response.status_code == 204

    response = client.get("/api/creators/creator-1/follow")
    assert response.json()["follower_count"] == 0


def test_follow_requires_auth(monkeypatch):
    supabase = FakeSupabase([
        {"id": "creator-1", "username": "creator"},
    ])
    monkeypatch.setattr(creator_followers, "get_supabase_client", lambda: supabase)

    # Temporarily override security to simulate missing credentials
    app.dependency_overrides[creator_followers.security] = lambda: None
    try:
        response = TestClient(app).post("/api/creators/creator-1/follow")
        assert response.status_code == 401
    finally:
        app.dependency_overrides[creator_followers.security] = _override_security


def test_follow_self_forbidden(monkeypatch):
    supabase = FakeSupabase([
        {"id": "creator-1", "username": "creator"},
    ])
    monkeypatch.setattr(creator_followers, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(creator_followers, "decode_access_token", lambda _token: {"sub": "creator-1"})

    response = TestClient(app).post("/api/creators/creator-1/follow")
    assert response.status_code == 400


def test_follow_unknown_creator(monkeypatch):
    supabase = FakeSupabase([
        {"id": "creator-1", "username": "creator"},
    ])
    monkeypatch.setattr(creator_followers, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(creator_followers, "decode_access_token", lambda _token: {"sub": "follower-1"})

    response = TestClient(app).post("/api/creators/unknown/follow")
    assert response.status_code == 404
