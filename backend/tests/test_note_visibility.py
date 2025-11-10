import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.routes import notes  # noqa: E402


class FakeResponse:
    def __init__(self, data: Any):
        self.data = data
        if isinstance(data, list):
            self.count = len(data)
        elif data is None:
            self.count = 0
        else:
            self.count = 1


class FakeSupabase:
    def __init__(self, note: Dict[str, Any]):
        self.note = note
        self.current_table: Optional[str] = None
        self._operation: Optional[str] = None
        self._filters: List[tuple[str, Any]] = []
        self._update_data: Optional[Dict[str, Any]] = None

    def table(self, name: str):
        self.current_table = name
        self._operation = None
        self._filters = []
        self._update_data = None
        return self

    def select(self, *_args, **_kwargs):
        self._operation = "select"
        return self

    def update(self, data: Dict[str, Any]):
        self._operation = "update"
        self._update_data = data
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def order(self, *_args, **_kwargs):  # pragma: no cover - unused in tests but required for chaining
        return self

    def range(self, *_args, **_kwargs):  # pragma: no cover
        return self

    def single(self):
        return self

    def maybe_single(self):  # pragma: no cover
        return self

    def execute(self):
        if self.current_table == "notes":
            if self._operation == "update":
                if not any(col == "id" and value == self.note["id"] for col, value in self._filters):
                    return FakeResponse([])
                if self._update_data:
                    self.note.update(self._update_data)
                return FakeResponse([self.note])

            # select path
            matches = True
            for column, value in self._filters:
                if self.note.get(column) != value:
                    matches = False
                    break
            return FakeResponse(self.note if matches else None)

        if self.current_table == "note_salon_access":
            return FakeResponse([])

        return FakeResponse(None)


app = FastAPI()
app.include_router(notes.router, prefix="/api")


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def setup_module(_: object):
    app.dependency_overrides[notes.security] = _override_security


def teardown_module(_: object):
    app.dependency_overrides.pop(notes.security, None)


client = TestClient(app)


def test_map_note_summary_builds_share_url(monkeypatch):
    record = {
        "id": "note-1",
        "author_id": "user-1",
        "title": "Sample",
        "slug": "sample",
        "editor_type": "classic",
        "content_blocks": [],
        "is_paid": False,
        "price_points": 0,
        "allow_point_purchase": False,
        "allow_jpy_purchase": False,
        "tax_inclusive": True,
        "status": "draft",
        "updated_at": "2025-01-01T00:00:00Z",
        "categories": [],
        "visibility": "limited",
        "share_token": "abcdef",
    }

    summary = notes.map_note_summary(record)

    assert summary.visibility == "limited"
    expected_prefix = settings.frontend_url.rstrip("/")
    assert summary.share_url == f"{expected_prefix}/notes/share/abcdef"


def test_rotate_share_token_requires_limited_visibility(monkeypatch):
    note = {
        "id": "note-1",
        "author_id": "user-1",
        "visibility": "public",
        "share_token": None,
        "status": "draft",
        "editor_type": "classic",
        "content_blocks": [],
        "is_paid": False,
        "price_points": 0,
        "allow_point_purchase": False,
        "allow_jpy_purchase": False,
        "tax_inclusive": True,
        "updated_at": "2025-01-01T00:00:00Z",
        "categories": [],
    }

    fake_supabase = FakeSupabase(note)
    monkeypatch.setattr(notes, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(notes, "get_current_user_id", lambda _cred: "user-1")
    monkeypatch.setattr(notes, "_fetch_note_salon_ids", lambda _supabase, _note_id: [])

    response = client.post("/api/notes/note-1/share-token/rotate")

    assert response.status_code == 400
    assert fake_supabase.note.get("share_token") is None


def test_rotate_share_token_generates_new_value(monkeypatch):
    note = {
        "id": "note-1",
        "author_id": "user-1",
        "visibility": "limited",
        "share_token": "old-token",
        "status": "draft",
        "editor_type": "classic",
        "content_blocks": [],
        "is_paid": False,
        "price_points": 0,
        "allow_point_purchase": False,
        "allow_jpy_purchase": False,
        "tax_inclusive": True,
        "updated_at": "2025-01-01T00:00:00Z",
        "categories": [],
    }

    fake_supabase = FakeSupabase(note)
    monkeypatch.setattr(notes, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(notes, "get_current_user_id", lambda _cred: "user-1")
    monkeypatch.setattr(notes, "_fetch_note_salon_ids", lambda _supabase, _note_id: [])

    response = client.post("/api/notes/note-1/share-token/rotate")

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("visibility") == "limited"
    expected_prefix = f"{settings.frontend_url.rstrip('/')}/notes/share/"
    assert payload.get("share_url", "").startswith(expected_prefix)
    assert payload.get("share_url", "").endswith(fake_supabase.note["share_token"])
    assert fake_supabase.note["share_token"] != "old-token"


def test_get_note_via_share_token_returns_note(monkeypatch):
    note = {
        "id": "note-1",
        "author_id": "user-1",
        "title": "Limited Note",
        "slug": "limited-note",
        "visibility": "limited",
        "share_token": "good-token",
        "status": "published",
        "editor_type": "classic",
        "content_blocks": [],
        "is_paid": False,
        "price_points": 0,
        "allow_point_purchase": False,
        "allow_jpy_purchase": False,
        "tax_inclusive": True,
        "updated_at": "2025-01-01T00:00:00Z",
        "categories": [],
        "users": {"username": "author"},
        "published_at": "2025-01-01T00:00:00Z",
    }

    fake_supabase = FakeSupabase(note)
    monkeypatch.setattr(notes, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(notes, "_fetch_note_salon_ids", lambda _supabase, _note_id: [])

    response = client.get("/api/notes/share/good-token")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "note-1"
    assert body["author_username"] == "author"


def test_get_note_via_share_token_rejects_non_limited(monkeypatch):
    note = {
        "id": "note-1",
        "author_id": "user-1",
        "title": "Public note",
        "slug": "public-note",
        "visibility": "public",
        "share_token": "public-token",
        "status": "published",
        "editor_type": "classic",
        "content_blocks": [],
        "is_paid": False,
        "price_points": 0,
        "allow_point_purchase": False,
        "allow_jpy_purchase": False,
        "tax_inclusive": True,
        "updated_at": "2025-01-01T00:00:00Z",
        "categories": [],
        "users": {"username": "author"},
        "published_at": "2025-01-01T00:00:00Z",
    }

    fake_supabase = FakeSupabase(note)
    monkeypatch.setattr(notes, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(notes, "_fetch_note_salon_ids", lambda _supabase, _note_id: [])

    response = client.get("/api/notes/share/public-token")

    assert response.status_code == 404


def test_get_public_note_filters_paid_rich_content(monkeypatch):
    note = {
        "id": "note-1",
        "author_id": "user-1",
        "title": "Rich note",
        "slug": "rich-note",
        "visibility": "public",
        "status": "published",
        "editor_type": "note",
        "is_paid": True,
        "price_points": 100,
        "allow_point_purchase": True,
        "allow_jpy_purchase": False,
        "tax_inclusive": True,
        "requires_login": False,
        "content_blocks": [],
        "rich_content": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"access": "public"},
                    "content": [{"type": "text", "text": "free"}],
                },
                {
                    "type": "paragraph",
                    "attrs": {"access": "paid"},
                    "content": [{"type": "text", "text": "paid"}],
                },
            ],
        },
        "categories": [],
        "allow_share_unlock": False,
        "tax_rate": 10.0,
        "users": {"username": "author"},
    }

    fake_supabase = FakeSupabase(note)
    monkeypatch.setattr(notes, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(notes, "_fetch_note_salon_ids", lambda *_args: [])
    monkeypatch.setattr(notes, "_user_has_purchased", lambda *_args: False)
    monkeypatch.setattr(notes, "_user_has_active_salon_access", lambda *_args: False)

    response = client.get("/api/notes/public/rich-note")

    assert response.status_code == 200
    body = response.json()
    assert body["editor_type"] == "note"
    rich = body.get("rich_content") or {}
    assert rich.get("type") == "doc"
    content = rich.get("content") or []
    assert len(content) == 1
    assert content[0].get("attrs", {}).get("access") == "public"
    inner = content[0].get("content", [])
    assert inner and inner[0].get("text") == "free"
