from __future__ import annotations

import os
import sys
from types import SimpleNamespace
import base64

import pytest
from fastapi import HTTPException, status

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.services import secret_memo


class SecretMemoTableStub:
    def __init__(self, supabase: "SecretMemoSupabaseStub") -> None:
        self._supabase = supabase
        self._mode = "select"
        self._filters: dict[str, str] = {}
        self._limit: int | None = None
        self._payload: list[dict] = []

    def select(self, *_columns):
        self._mode = "select"
        return self

    def eq(self, column: str, value: str):
        self._filters[column] = value
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def upsert(self, payload):
        self._mode = "upsert"
        self._payload = payload if isinstance(payload, list) else [payload]
        return self

    def execute(self):
        if self._mode == "select":
            rows = []
            for row in self._supabase.rows:
                if all(row.get(column) == value for column, value in self._filters.items()):
                    rows.append(dict(row))
            if self._limit is not None:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)

        for entry in self._payload:
            data = dict(entry)
            data.setdefault("updated_at", self._supabase.timestamp)
            existing = next((row for row in self._supabase.rows if row.get("key") == data.get("key")), None)
            if existing:
                existing.update(data)
            else:
                self._supabase.rows.append(data)
        return SimpleNamespace(data=self._payload)


class SecretMemoSupabaseStub:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.timestamp = "2025-11-23T15:00:00+00:00"

    def table(self, name: str) -> SecretMemoTableStub:  # pragma: no cover - simple proxy
        return SecretMemoTableStub(self)


def test_verify_secret_memo_password_accepts_correct_value(monkeypatch):
    monkeypatch.setattr(secret_memo.settings, "secret_memo_password", "kusano")
    secret_memo.verify_secret_memo_password("kusano")


def test_verify_secret_memo_password_rejects_invalid(monkeypatch):
    monkeypatch.setattr(secret_memo.settings, "secret_memo_password", "kusano")
    with pytest.raises(HTTPException) as exc:
        secret_memo.verify_secret_memo_password("invalid")
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_get_secret_memo_record_returns_empty_when_absent():
    client = SecretMemoSupabaseStub()
    record = secret_memo.get_secret_memo_record(client=client)
    assert record.content == ""
    assert record.updated_at is None
    assert record.updated_by is None


def test_save_secret_memo_persists_content():
    client = SecretMemoSupabaseStub()
    record = secret_memo.save_secret_memo("メモ", actor_id="admin-1", client=client)
    assert record.content == "メモ"
    assert record.updated_by == "admin-1"
    assert record.updated_at == client.timestamp


def test_add_secret_memo_file_appends_entry(monkeypatch):
    client = SecretMemoSupabaseStub()
    monkeypatch.setattr(secret_memo, "uuid4", lambda: "file-1")
    monkeypatch.setattr(secret_memo, "_now_iso", lambda: "2025-11-23T12:00:00+00:00")

    result = secret_memo.add_secret_memo_file(
        filename="evidence.txt",
        mime_type="text/plain",
        data_base64="aGVsbG8gd29ybGQ=",
        actor_id="admin-1",
        client=client,
    )

    assert result.id == "file-1"
    assert result.size == 11

    record = secret_memo.get_secret_memo_record(client)
    assert len(record.files) == 1
    stored = record.files[0]
    assert stored.filename == "evidence.txt"
    assert stored.data_base64 == "aGVsbG8gd29ybGQ="


def test_add_secret_memo_file_rejects_large_payload(monkeypatch):
    client = SecretMemoSupabaseStub()
    large_payload = base64.b64encode(b"x" * (secret_memo.SECRET_MEMO_MAX_FILE_SIZE + 1)).decode()
    with pytest.raises(HTTPException) as exc:
        secret_memo.add_secret_memo_file(
            filename="huge.bin",
            mime_type="application/octet-stream",
            data_base64=large_payload,
            actor_id="admin",
            client=client,
        )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_remove_secret_memo_file_deletes_entry(monkeypatch):
    rows = [
        {
            "key": secret_memo.SECRET_MEMO_KEY,
            "value": {
                "content": "top secret",
                "files": [
                    {
                        "id": "file-1",
                        "filename": "memo.pdf",
                        "mime_type": "application/pdf",
                        "size": 100,
                        "data_base64": base64.b64encode(b"PDF").decode(),
                        "uploaded_at": "2025-11-23T10:00:00+00:00",
                    }
                ],
            },
            "updated_by": "admin-1",
        }
    ]
    client = SecretMemoSupabaseStub(rows=rows)

    record = secret_memo.remove_secret_memo_file(file_id="file-1", actor_id="admin-2", client=client)

    assert len(record.files) == 0
    assert record.content == "top secret"


def test_remove_secret_memo_file_raises_when_missing():
    client = SecretMemoSupabaseStub()
    with pytest.raises(HTTPException) as exc:
        secret_memo.remove_secret_memo_file(file_id="missing", actor_id="admin", client=client)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
