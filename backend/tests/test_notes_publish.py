import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import notes


app = FastAPI()
app.include_router(notes.router, prefix="/api")


def _override_security():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def setup_module(_: object):
    app.dependency_overrides[notes.security] = _override_security


def teardown_module(_: object):
    app.dependency_overrides.pop(notes.security, None)


class FakeSupabase:
    def __init__(self, note_record):
        self.storage = {
            "notes": [dict(note_record)],
        }

    def table(self, name: str):
        return FakeQuery(self, name)


class FakeQuery:
    def __init__(self, parent: "FakeSupabase", table: str):
        self.parent = parent
        self.table = table
        self.operation = None
        self.filters = []
        self.single_mode = False
        self.limit_value = None

    def select(self, _columns: str):
        self.operation = ("select", _columns)
        return self

    def update(self, payload):
        self.operation = ("update", dict(payload))
        return self

    def eq(self, column: str, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column: str, value):
        self.filters.append(("neq", column, value))
        return self

    def single(self):
        self.single_mode = True
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def execute(self):
        rows = [dict(row) for row in self.parent.storage.get(self.table, [])]
        for op, column, value in self.filters:
            if op == "eq":
                rows = [row for row in rows if row.get(column) == value]
            elif op == "neq":
                rows = [row for row in rows if row.get(column) != value]

        if self.operation and self.operation[0] == "select":
            if self.limit_value is not None:
                rows = rows[: self.limit_value]
            if self.single_mode:
                data = rows[0] if rows else None
                return SimpleNamespace(data=data)
            return SimpleNamespace(data=rows)

        if self.operation and self.operation[0] == "update":
            update_payload = self.operation[1]
            updated_rows = []
            table_rows = self.parent.storage.get(self.table, [])
            for index, row in enumerate(table_rows):
                match = True
                for op, column, value in self.filters:
                    if op == "eq" and row.get(column) != value:
                        match = False
                        break
                    if op == "neq" and row.get(column) == value:
                        match = False
                        break
                if match:
                    updated = {**row, **update_payload}
                    table_rows[index] = updated
                    updated_rows.append(dict(updated))
            self.parent.storage[self.table] = table_rows
            return SimpleNamespace(data=updated_rows)

        raise AssertionError("Unsupported operation")


def test_publish_paid_note_with_only_jpy(monkeypatch):
    note_id = "note-123"
    note_record = {
        "id": note_id,
        "author_id": "author-1",
        "title": "Paid note",
        "slug": "paid-note",
        "content_blocks": [],
        "is_paid": True,
        "price_points": 0,
        "price_jpy": 1500,
        "allow_point_purchase": False,
        "allow_jpy_purchase": True,
        "status": "draft",
        "visibility": "public",
    }
    supabase = FakeSupabase(note_record)
    monkeypatch.setattr(notes, "get_supabase", lambda: supabase)
    monkeypatch.setattr(notes, "get_current_user_id", lambda _: "author-1")
    monkeypatch.setattr(notes, "generate_unique_slug", lambda *_args, **_kwargs: "paid-note")
    monkeypatch.setattr(notes, "_fetch_note_salon_ids", lambda *_args, **_kwargs: [])

    client = TestClient(app)

    response = client.post(f"/api/notes/{note_id}/publish")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "published"
    assert payload["price_jpy"] == 1500
    assert payload["allow_jpy_purchase"] is True
