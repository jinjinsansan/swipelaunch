import os
import sys
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import public, lp  # noqa: E402


class FakeResponse:
    def __init__(self, data: Any):
        self.data = data
        if isinstance(data, list):
            self.count = len(data)
        elif data is None:
            self.count = 0
        else:
            self.count = 1


class _LandingPageQuery:
    def __init__(self, lp_record: Dict[str, Any]):
        self.lp_record = lp_record
        self.filters: list[tuple[str, Any]] = []
        self.is_single = False
        self.is_update = False
        self.update_payload: Dict[str, Any] = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column: str, value: Any):
        self.filters.append((column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _value: int):
        return self

    def single(self):
        self.is_single = True
        return self

    def update(self, payload: Dict[str, Any]):
        self.is_update = True
        self.update_payload = payload or {}
        return self

    def insert(self, _payload: Any):
        return self

    def execute(self):
        if self.is_update:
            self.lp_record.update(self.update_payload)
            return FakeResponse([dict(self.lp_record)])

        matches = all(self.lp_record.get(column) == value for column, value in self.filters)
        if not matches:
            return FakeResponse(None if self.is_single else [])

        if self.is_single:
            return FakeResponse(dict(self.lp_record))
        return FakeResponse([dict(self.lp_record)])


class _StaticQuery:
    def __init__(self, data: Any):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    def update(self, *_args, **_kwargs):
        return self

    def insert(self, *_args, **_kwargs):
        return self

    def execute(self):
        return FakeResponse(self._data)


class FakeSupabaseLP:
    def __init__(self, lp_record: Dict[str, Any]):
        self.lp_record = lp_record

    def table(self, name: str):
        if name == "landing_pages":
            return _LandingPageQuery(self.lp_record)
        if name in {"lp_steps", "lp_ctas", "lp_event_logs", "salons", "users"}:
            return _StaticQuery([])
        return _StaticQuery([])


def _make_lp_record(visibility: str, token: str = "share-token") -> Dict[str, Any]:
    return {
        "id": "lp-1",
        "seller_id": "user-1",
        "title": "Sample LP",
        "slug": "sample-lp",
        "status": "published",
        "visibility": visibility,
        "swipe_direction": "vertical",
        "is_fullscreen": False,
        "show_swipe_hint": False,
        "fullscreen_media": False,
        "floating_cta": False,
        "total_views": 0,
        "total_cta_clicks": 0,
        "product_id": None,
        "salon_id": None,
        "meta_title": None,
        "meta_description": None,
        "meta_image_url": None,
        "meta_site_name": None,
        "custom_theme_hex": None,
        "custom_theme_shades": None,
        "footer_cta_config": None,
        "owner": None,
        "share_token": token,
        "share_token_rotated_at": "2025-01-01T00:00:00Z",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


def test_fetch_lp_share_allows_limited(monkeypatch):
    record = _make_lp_record("limited", token="limited-token")
    fake_supabase = FakeSupabaseLP(record)
    monkeypatch.setattr(public, "get_supabase", lambda: fake_supabase)

    response = public._fetch_lp_by_share_token("limited-token")

    assert response.visibility == "limited"
    assert response.share_url and response.share_url.endswith("limited-token")


def test_fetch_lp_share_allows_public(monkeypatch):
    record = _make_lp_record("public", token="public-token")
    fake_supabase = FakeSupabaseLP(record)
    monkeypatch.setattr(public, "get_supabase", lambda: fake_supabase)

    response = public._fetch_lp_by_share_token("public-token")

    assert response.visibility == "public"
    assert response.share_url and response.share_url.endswith("public-token")


def test_fetch_lp_share_rejects_private(monkeypatch):
    record = _make_lp_record("private", token="private-token")
    fake_supabase = FakeSupabaseLP(record)
    monkeypatch.setattr(public, "get_supabase", lambda: fake_supabase)

    with pytest.raises(HTTPException) as exc:
        public._fetch_lp_by_share_token("private-token")

    assert exc.value.status_code == 404


app = FastAPI()
app.include_router(lp.router, prefix="/api")


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


@pytest.fixture(autouse=True)
def _override_dependencies(monkeypatch):
    app.dependency_overrides[lp.security] = _override_security
    yield
    app.dependency_overrides.pop(lp.security, None)


client = TestClient(app)


def test_update_lp_keeps_share_token_when_public(monkeypatch):
    record = _make_lp_record("limited", token="keep-token")
    fake_supabase = FakeSupabaseLP(record)

    monkeypatch.setattr(lp, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(lp, "get_current_user_id", lambda _cred: "user-1")

    response = client.put("/api/lp/lp-1", json={"visibility": "public"})

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["visibility"] == "public"
    assert body.get("share_url", "").endswith("keep-token")
    assert fake_supabase.lp_record["share_token"] == "keep-token"
