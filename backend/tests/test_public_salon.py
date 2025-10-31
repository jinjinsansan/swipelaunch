from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.constants.subscription_plans import SUBSCRIPTION_PLANS
from app.routes import public


class FakeQuery:
    def __init__(self, supabase: "FakeSupabase", table: str) -> None:
        self._supabase = supabase
        self._table = table
        self._filters: Dict[str, Any] = {}
        self._count: Optional[str] = None
        self._limit: Optional[int] = None
        self._single = False

    def select(self, *_args, count: Optional[str] = None, **_kwargs):
        self._count = count
        return self

    def eq(self, key: str, value: Any):
        self._filters[key] = value
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def single(self):
        self._single = True
        return self

    def _apply_filters(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._filters:
            return list(rows)
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if all(row.get(k) == v for k, v in self._filters.items()):
                filtered.append(row)
        return filtered

    def execute(self):
        rows = list(self._supabase.tables.get(self._table, []))
        filtered = self._apply_filters(rows)

        if self._limit is not None:
            filtered = filtered[: self._limit]

        if self._count == "exact":
            return SimpleNamespace(data=filtered, count=len(filtered))

        if self._single:
            return SimpleNamespace(data=filtered[0] if filtered else None)

        return SimpleNamespace(data=filtered)


class FakeSupabase:
    def __init__(self, initial_tables: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        if initial_tables:
            for name, rows in initial_tables.items():
                self.tables[name] = [dict(row) for row in rows]

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(public.router, prefix="/api")
    return TestClient(app)


def test_get_public_salon_returns_details(monkeypatch, app_client):
    plan = SUBSCRIPTION_PLANS[0]
    fake_db = {
        "salons": [
            {
                "id": "salon-1",
                "owner_id": "owner-1",
                "title": "スパイダー競馬予想サロン",
                "description": "毎週の予想をシェア",
                "thumbnail_url": "https://example.com/thumb.jpg",
                "subscription_plan_id": plan.subscription_plan_id,
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            }
        ],
        "users": [
            {
                "id": "owner-1",
                "username": "spider-master",
                "display_name": "スパイダー",
                "profile_image_url": "https://example.com/avatar.jpg",
            }
        ],
        "salon_memberships": [
            {"id": "mem-1", "salon_id": "salon-1", "user_id": "member-1", "status": "ACTIVE"},
            {"id": "mem-2", "salon_id": "salon-1", "user_id": "member-2", "status": "ACTIVE"},
        ],
    }

    monkeypatch.setattr(public, "get_supabase", lambda: FakeSupabase(fake_db))

    response = app_client.get("/api/public/salons/salon-1")
    assert response.status_code == 200

    payload = response.json()
    assert payload["id"] == "salon-1"
    assert payload["title"] == "スパイダー競馬予想サロン"
    assert payload["plan"]["subscription_plan_id"] == plan.subscription_plan_id
    assert payload["member_count"] == 2
    assert payload["is_member"] is False
    assert payload["owner"]["username"] == "spider-master"


def test_get_public_salon_marks_member(monkeypatch, app_client):
    plan = SUBSCRIPTION_PLANS[0]
    fake_db = {
        "salons": [
            {
                "id": "salon-1",
                "owner_id": "owner-1",
                "title": "サロン",
                "description": None,
                "thumbnail_url": None,
                "subscription_plan_id": plan.subscription_plan_id,
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            }
        ],
        "users": [
            {"id": "owner-1", "username": "owner", "display_name": None, "profile_image_url": None}
        ],
        "salon_memberships": [
            {"id": "mem-active", "salon_id": "salon-1", "user_id": "viewer-1", "status": "ACTIVE"}
        ],
    }

    monkeypatch.setattr(public, "get_supabase", lambda: FakeSupabase(fake_db))
    monkeypatch.setattr(public, "decode_access_token", lambda token: {"sub": "viewer-1"})

    response = app_client.get("/api/public/salons/salon-1", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["is_member"] is True
    assert payload["membership_status"] == "ACTIVE"


def test_get_public_salon_inactive_returns_404(monkeypatch, app_client):
    plan = SUBSCRIPTION_PLANS[0]
    fake_db = {
        "salons": [
            {
                "id": "salon-1",
                "owner_id": "owner-1",
                "title": "非公開サロン",
                "description": None,
                "thumbnail_url": None,
                "subscription_plan_id": plan.subscription_plan_id,
                "is_active": False,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            }
        ],
        "users": [
            {"id": "owner-1", "username": "owner", "display_name": None, "profile_image_url": None}
        ],
        "salon_memberships": [],
    }

    monkeypatch.setattr(public, "get_supabase", lambda: FakeSupabase(fake_db))

    response = app_client.get("/api/public/salons/salon-1")
    assert response.status_code == 404
