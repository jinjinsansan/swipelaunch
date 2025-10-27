import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.routes import notes


app = FastAPI()
app.include_router(notes.router, prefix="/api")


class FakeRPCResponse:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error


class FakeSupabaseSuccess:
    class _Builder:
        def execute(self_inner):
            return FakeRPCResponse(
                data=[
                    {
                        "purchase_id": "purchase-123",
                        "points_spent": 300,
                        "remaining_points": 700,
                        "purchased_at": "2025-01-01T00:00:00Z",
                    }
                ]
            )

    def rpc(self, name: str, params: dict):
        assert name == "purchase_note_with_points"
        assert "p_note_id" in params and "p_buyer_id" in params
        return self._Builder()


class FakeSupabaseConflict:
    class _Builder:
        def execute(self_inner):
            raise APIError({
                "message": "既に購入済みです",
                "code": "23505",
                "details": None,
                "hint": None,
            })

    def rpc(self, name: str, params: dict):
        return self._Builder()


class FakeSupabaseUnknown:
    class _Builder:
        def execute(self_inner):
            return FakeRPCResponse(error=type("Error", (), {"message": "不明なエラー", "code": None})())

    def rpc(self, name: str, params: dict):
        return self._Builder()


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def setup_module(_: object):
    app.dependency_overrides[notes.security] = _override_security


def teardown_module(_: object):
    app.dependency_overrides.pop(notes.security, None)


def _setup_common(monkeypatch, supabase_instance):
    monkeypatch.setattr(notes, "get_supabase", lambda: supabase_instance)
    monkeypatch.setattr(notes, "get_current_user_id", lambda _: "user-123")


def test_purchase_note_success(monkeypatch):
    _setup_common(monkeypatch, FakeSupabaseSuccess())
    client = TestClient(app)

    response = client.post("/api/notes/note-abc/purchase")

    assert response.status_code == 201
    payload = response.json()
    assert payload["note_id"] == "note-abc"
    assert payload["points_spent"] == 300
    assert payload["remaining_points"] == 700
    assert payload["purchased_at"] == "2025-01-01T00:00:00Z"


def test_purchase_note_conflict(monkeypatch):
    _setup_common(monkeypatch, FakeSupabaseConflict())
    client = TestClient(app)

    response = client.post("/api/notes/note-abc/purchase")

    assert response.status_code == 409
    assert response.json()["detail"] == "既に購入済みです"


def test_purchase_note_unknown_error(monkeypatch):
    _setup_common(monkeypatch, FakeSupabaseUnknown())
    client = TestClient(app)

    response = client.post("/api/notes/note-abc/purchase")

    assert response.status_code == 500
    assert response.json()["detail"] == "不明なエラー"
