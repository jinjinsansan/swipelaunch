from __future__ import annotations

import os
import sys
from types import SimpleNamespace

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
    record = secret_memo.save_secret_memo("極秘", actor_id="admin-1", client=client)
    assert record.content == "極秘"
    assert record.updated_by == "admin-1"
    assert record.updated_at == client.timestamp
