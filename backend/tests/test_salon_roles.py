import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.models.salon_roles import SalonRolePermissions
from app.routes import salon_roles


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
        self._operation: str = "select"
        self._payload: Any = None
        self._count_mode: Optional[str] = None
        self._single: bool = False
        self._maybe_single: bool = False

    @property
    def _table(self) -> List[Dict[str, Any]]:
        return self.client.tables[self.name]

    def _matching_rows(self) -> List[Dict[str, Any]]:
        matches = []
        for row in self._table:
            keep = True
            for op, field, value in self._filters:
                current = row.get(field)
                if op == "eq" and current != value:
                    keep = False
                    break
                if op == "in" and current not in value:
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

    def in_(self, field: str, values: Iterable[Any]):
        self._filters.append(("in", field, list(values)))
        return self

    def order(self, field: str, desc: bool = False):
        self._order.append((field, desc))
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
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

    def delete(self):
        self._operation = "delete"
        return self

    def execute(self):
        if self._operation == "insert":
            record = deepcopy(self._payload)
            record.setdefault("id", str(uuid4()))
            now = datetime.now(timezone.utc).isoformat()
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

        if self._operation == "delete":
            targets = {id(row) for row in self._matching_rows()}
            self.client.tables[self.name] = [row for row in self._table if id(row) not in targets]
            return _Response(data=[])

        rows = [deepcopy(row) for row in self._matching_rows()]

        for field, desc in reversed(self._order):
            rows.sort(key=lambda item: item.get(field), reverse=desc)

        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]

        if self._single or self._maybe_single:
            if rows:
                return _Response(data=rows[0])
            return _Response(data=None)

        count = len(self._matching_rows()) if self._count_mode == "exact" else None
        return _Response(data=rows, count=count)


def _patch_permissions(monkeypatch, manage_roles: bool = True, manage_members: bool = True):
    permissions = SalonRolePermissions(
        manage_feed=manage_roles,
        manage_events=manage_roles,
        manage_assets=manage_roles,
        manage_announcements=manage_roles,
        manage_members=manage_members,
        manage_roles=manage_roles,
    )

    def _fake_permissions(_client, _salon_id, _user_id, *, is_owner: bool):
        if is_owner:
            return SalonRolePermissions(
                manage_feed=True,
                manage_events=True,
                manage_assets=True,
                manage_announcements=True,
                manage_members=True,
                manage_roles=True,
            )
        return permissions

    monkeypatch.setattr(salon_roles, "get_user_permissions", _fake_permissions)


def _patch_current_user(monkeypatch, user_id: str):
    monkeypatch.setattr(salon_roles, "_get_current_user", lambda _: {"id": user_id, "username": "tester"})


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(salon_roles.router, prefix="/api")
    return TestClient(app)


def test_list_roles_requires_permission(monkeypatch, app_client):
    fake_supabase = FakeSupabase({"salon_roles": [], "salon_member_roles": []})
    monkeypatch.setattr(salon_roles, "get_supabase_client", lambda: fake_supabase)
    monkeypatch.setattr(
        salon_roles,
        "_get_salon_and_access",
        lambda client, salon_id, user_id: ({"id": salon_id, "owner_id": "owner"}, False),
    )
    _patch_current_user(monkeypatch, "member-1")
    _patch_permissions(monkeypatch, manage_roles=False)

    response = app_client.get(
        "/api/salons/salon-1/roles",
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 403


def test_create_role_success(monkeypatch, app_client):
    fake_supabase = FakeSupabase({"salon_roles": [], "salon_member_roles": []})
    monkeypatch.setattr(salon_roles, "get_supabase_client", lambda: fake_supabase)
    monkeypatch.setattr(
        salon_roles,
        "_get_salon_and_access",
        lambda client, salon_id, user_id: ({"id": salon_id, "owner_id": "owner"}, False),
    )
    _patch_current_user(monkeypatch, "manager-1")
    _patch_permissions(monkeypatch, manage_roles=True)

    payload = {
        "name": "モデレーター",
        "description": "投稿管理",
        "manage_feed": True,
        "manage_events": False,
        "manage_assets": False,
        "manage_announcements": True,
        "manage_members": False,
        "manage_roles": False,
    }

    response = app_client.post(
        "/api/salons/salon-1/roles",
        json=payload,
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "モデレーター"
    assert body["salon_id"] == "salon-1"
    assert body["manage_feed"] is True
    assert len(fake_supabase.tables["salon_roles"]) == 1


def test_assign_role_to_member(monkeypatch, app_client):
    fake_supabase = FakeSupabase(
        {
            "salon_roles": [
                {
                    "id": "role-1",
                    "salon_id": "salon-1",
                    "name": "スタッフ",
                    "is_default": False,
                    "manage_members": False,
                    "manage_roles": False,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                }
            ],
            "salon_member_roles": [],
            "salon_memberships": [
                {
                    "salon_id": "salon-1",
                    "user_id": "member-9",
                    "status": "ACTIVE",
                }
            ],
        }
    )

    monkeypatch.setattr(salon_roles, "get_supabase_client", lambda: fake_supabase)
    monkeypatch.setattr(
        salon_roles,
        "_get_salon_and_access",
        lambda client, salon_id, user_id: ({"id": salon_id, "owner_id": "owner"}, False),
    )
    _patch_current_user(monkeypatch, "manager-1")
    _patch_permissions(monkeypatch, manage_roles=True, manage_members=True)

    response = app_client.post(
        "/api/salons/salon-1/roles/role-1/assign",
        json={"user_id": "member-9"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role_id"] == "role-1"
    assert body["user_id"] == "member-9"
    assert len(fake_supabase.tables["salon_member_roles"]) == 1
