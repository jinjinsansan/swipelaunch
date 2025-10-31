import os
import sys
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import salon_announcements
from app.models.salon_roles import SalonRolePermissions


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
        self._single: bool = False
        self._operation: str = "select"
        self._payload: Any = None
        self._count_mode: Optional[str] = None

    @property
    def _table(self) -> List[Dict[str, Any]]:
        return self.client.tables[self.name]

    def _matching_rows(self) -> List[Dict[str, Any]]:
        matches = []
        for row in self._table:
            matched = True
            for op, field, value in self._filters:
                current = row.get(field)
                if op == "eq" and current != value:
                    matched = False
                    break
            if matched:
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

    def single(self):
        self._single = True
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
            targets = set(id(row) for row in self._matching_rows())
            self.client.tables[self.name] = [row for row in self._table if id(row) not in targets]
            return _Response(data=[])

        rows = [deepcopy(row) for row in self._matching_rows()]

        for field, desc in reversed(self._order):
            rows.sort(key=lambda item: item.get(field), reverse=desc)

        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]

        if self._single:
            return _Response(data=rows[0] if rows else None)

        count = len(self._matching_rows()) if self._count_mode == "exact" else None
        return _Response(data=rows, count=count)


def _patch_permissions(monkeypatch, user_id: str, owner_id: str, allow_manage: bool = True):
    monkeypatch.setattr(salon_announcements, "_get_current_user", lambda _: {"id": user_id, "username": "user"})
    monkeypatch.setattr(
        salon_announcements,
        "_get_salon_and_access",
        lambda client, salon_id, _: ({"id": salon_id, "owner_id": owner_id}, allow_manage),
    )
    monkeypatch.setattr(
        salon_announcements,
        "get_user_permissions",
        lambda client, salon_id, _, *, is_owner: SalonRolePermissions(
            manage_feed=True,
            manage_events=True,
            manage_assets=True,
            manage_announcements=True,
            manage_members=True,
            manage_roles=True,
        )
        if is_owner
        else SalonRolePermissions(
            manage_feed=allow_manage,
            manage_events=allow_manage,
            manage_assets=allow_manage,
            manage_announcements=allow_manage,
            manage_members=allow_manage,
            manage_roles=allow_manage,
        ),
    )


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(salon_announcements.router, prefix="/api")
    return TestClient(app)


@pytest.mark.asyncio
async def test_list_announcements_filters_unpublished(monkeypatch, app_client):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=2)).isoformat()
    past = (now - timedelta(days=2)).isoformat()

    fake_supabase = FakeSupabase(
        {
            "salon_announcements": [
                {
                    "id": "ann1",
                    "salon_id": "salon-1",
                    "author_id": "owner-1",
                    "title": "Published",
                    "body": "Visible",
                    "is_pinned": True,
                    "is_published": True,
                    "start_at": past,
                    "end_at": None,
                    "created_at": past,
                    "updated_at": past,
                },
                {
                    "id": "ann2",
                    "salon_id": "salon-1",
                    "author_id": "owner-1",
                    "title": "Draft",
                    "body": "Hidden",
                    "is_pinned": False,
                    "is_published": False,
                    "start_at": past,
                    "end_at": None,
                    "created_at": past,
                    "updated_at": past,
                },
                {
                    "id": "ann3",
                    "salon_id": "salon-1",
                    "author_id": "owner-1",
                    "title": "Future",
                    "body": "Not yet",
                    "is_pinned": False,
                    "is_published": True,
                    "start_at": future,
                    "end_at": None,
                    "created_at": past,
                    "updated_at": past,
                },
            ]
        }
    )

    monkeypatch.setattr(salon_announcements, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "member-1", "owner-1", allow_manage=False)

    response = app_client.get(
        "/api/salons/salon-1/announcements",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == "ann1"


@pytest.mark.asyncio
async def test_create_announcement_requires_owner(monkeypatch, app_client):
    fake_supabase = FakeSupabase({"salon_announcements": []})
    monkeypatch.setattr(salon_announcements, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "owner-1", "owner-1", allow_manage=True)

    response = app_client.post(
        "/api/salons/salon-1/announcements",
        headers={"Authorization": "Bearer token"},
        json={
            "title": "新着情報",
            "body": "詳細内容",
            "is_pinned": True,
            "is_published": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "新着情報"
    assert payload["is_pinned"] is True
    assert len(fake_supabase.tables["salon_announcements"]) == 1


@pytest.mark.asyncio
async def test_update_announcement_validates_schedule(monkeypatch, app_client):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=2)).isoformat()
    record = {
        "id": "ann-edit",
        "salon_id": "salon-1",
        "author_id": "owner-1",
        "title": "既存",
        "body": "内容",
        "is_pinned": False,
        "is_published": True,
        "start_at": now.isoformat(),
        "end_at": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    fake_supabase = FakeSupabase({"salon_announcements": [record]})

    monkeypatch.setattr(salon_announcements, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "owner-1", "owner-1", allow_manage=True)

    response = app_client.patch(
        "/api/salons/salon-1/announcements/ann-edit",
        headers={"Authorization": "Bearer token"},
        json={"end_at": now.isoformat(), "start_at": future},
    )

    assert response.status_code == 400
    assert "終了日時" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_announcement(monkeypatch, app_client):
    record = {
        "id": "ann-del",
        "salon_id": "salon-1",
        "author_id": "owner-1",
        "title": "削除対象",
        "body": "body",
        "is_pinned": False,
        "is_published": True,
        "start_at": None,
        "end_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    fake_supabase = FakeSupabase({"salon_announcements": [record]})

    monkeypatch.setattr(salon_announcements, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "owner-1", "owner-1", allow_manage=True)

    response = app_client.delete(
        "/api/salons/salon-1/announcements/ann-del",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 204
    assert fake_supabase.tables["salon_announcements"] == []
