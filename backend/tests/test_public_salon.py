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
        self._in_filters: Dict[str, set[Any]] = {}
        self._count: Optional[str] = None
        self._limit: Optional[int] = None
        self._single = False

    def select(self, *_args, count: Optional[str] = None, **_kwargs):
        self._count = count
        return self

    def eq(self, key: str, value: Any):
        self._filters[key] = value
        return self

    def in_(self, key: str, values: Iterable[Any]):
        self._in_filters[key] = {v for v in values}
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def single(self):
        self._single = True
        return self

    def _apply_filters(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._filters and not self._in_filters:
            return list(rows)
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if not all(row.get(k) == v for k, v in self._filters.items()):
                continue
            in_match = True
            for key, values in self._in_filters.items():
                if row.get(key) not in values:
                    in_match = False
                    break
            if not in_match:
                continue
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


def test_get_public_salon_handles_unknown_plan(monkeypatch, app_client):
    fake_db = {
        "salons": [
            {
                "id": "salon-unknown",
                "owner_id": "owner-1",
                "title": "未知プランサロン",
                "description": "",
                "thumbnail_url": None,
                "subscription_plan_id": "plan-custom",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            }
        ],
        "users": [
            {
                "id": "owner-1",
                "username": "owner",
                "display_name": None,
                "profile_image_url": None,
            }
        ],
        "salon_memberships": [],
    }

    monkeypatch.setattr(public, "get_supabase", lambda: FakeSupabase(fake_db))

    response = app_client.get("/api/public/salons/salon-unknown")
    assert response.status_code == 200

    payload = response.json()
    assert payload["plan"]["subscription_plan_id"] == "plan-custom"
    assert payload["plan"]["label"] == "プラン情報未設定"
    assert payload["plan"]["points"] == 0


def test_get_public_lp_includes_linked_salon(monkeypatch, app_client):
    fake_db = {
        "landing_pages": [
            {
                "id": "lp-1",
                "seller_id": "owner-1",
                "title": "サロン紹介LP",
                "slug": "sample-lp",
                "status": "published",
                "swipe_direction": "vertical",
                "is_fullscreen": False,
                "show_swipe_hint": False,
                "fullscreen_media": False,
                "floating_cta": False,
                "total_views": 12,
                "total_cta_clicks": 0,
                "product_id": None,
                "salon_id": "salon-1",
                "meta_title": None,
                "meta_description": None,
                "meta_image_url": None,
                "meta_site_name": None,
                "custom_theme_hex": None,
                "custom_theme_shades": None,
                "owner": {"username": "ownername", "email": "owner@example.com"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            }
        ],
        "lp_steps": [],
        "lp_ctas": [],
        "salons": [
            {
                "id": "salon-1",
                "owner_id": "owner-1",
                "title": "オンラインサロンA",
                "category": "business",
                "thumbnail_url": "https://example.com/thumb.png",
                "is_active": True,
            }
        ],
        "users": [
            {"id": "owner-1", "username": "ownername"}
        ],
    }

    monkeypatch.setattr(public, "get_supabase", lambda: FakeSupabase(fake_db))

    response = app_client.get("/api/public/sample-lp")
    assert response.status_code == 200

    payload = response.json()
    assert payload["salon_id"] == "salon-1"
    assert payload["linked_salon"] == {
        "id": "salon-1",
        "title": "オンラインサロンA",
        "public_path": "/salons/salon-1/public",
        "category": None,
        "owner_username": "ownername",
        "thumbnail_url": "https://example.com/thumb.png",
    }


def test_list_public_salons_filters(monkeypatch, app_client):
    plan_basic = SUBSCRIPTION_PLANS[0]
    plan_premium = SUBSCRIPTION_PLANS[-1]
    fake_db = {
        "salons": [
            {
                "id": "salon-basic",
                "owner_id": "owner-basic",
                "title": "ビギナー競馬サロン",
                "description": "はじめての方向け",
                "thumbnail_url": None,
                "category": "競馬",
                "subscription_plan_id": plan_basic.subscription_plan_id,
                "is_active": True,
                "created_at": "2024-01-05T00:00:00Z",
            },
            {
                "id": "salon-pro",
                "owner_id": "owner-pro",
                "title": "プロフェッショナル投資サロン",
                "description": "実践型コミュニティ",
                "thumbnail_url": "https://example.com/pro.jpg",
                "category": "ビジネス",
                "subscription_plan_id": plan_premium.subscription_plan_id,
                "is_active": True,
                "created_at": "2024-01-10T00:00:00Z",
            },
        ],
        "users": [
            {"id": "owner-basic", "username": "beginner", "display_name": "ビギナー", "profile_image_url": None},
            {"id": "owner-pro", "username": "protrader", "display_name": "プロトレーダー", "profile_image_url": "https://example.com/avatar.jpg"},
        ],
        "salon_memberships": [
            {"id": "m1", "salon_id": "salon-basic", "user_id": "u1", "status": "ACTIVE"},
            {"id": "m2", "salon_id": "salon-basic", "user_id": "u2", "status": "ACTIVE"},
            {"id": "m3", "salon_id": "salon-basic", "user_id": "u3", "status": "ACTIVE"},
            {"id": "m4", "salon_id": "salon-pro", "user_id": "u1", "status": "ACTIVE"},
        ],
    }

    monkeypatch.setattr(public, "get_supabase", lambda: FakeSupabase(fake_db))

    response = app_client.get("/api/public/salons", params={"price_range": "over_5000"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["data"][0]["id"] == "salon-pro"
    assert payload["data"][0]["category"] == "ビジネス"

    response_popular = app_client.get("/api/public/salons", params={"sort": "popular"})
    assert response_popular.status_code == 200
    popular = response_popular.json()
    assert popular["data"][0]["id"] == "salon-basic"  # most members

    response_seller = app_client.get("/api/public/salons", params={"seller_username": "protrader"})
    assert response_seller.status_code == 200
    seller_payload = response_seller.json()
    assert seller_payload["total"] == 1
    assert seller_payload["data"][0]["owner_username"] == "protrader"
