from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.models.operator_messages import OperatorMessageCreateRequest, OperatorMessageSegment  # noqa: E402
from app.routes import admin_messages, operator_messages  # noqa: E402
from app.services import operator_messages as message_service  # noqa: E402


class FakeQuery:
    def __init__(self, client: "FakeSupabase", name: str) -> None:
        self.client = client
        self.name = name
        self._operation: str = "select"
        self._payload: Any = None
        self._predicates: List[Any] = []
        self._order_field: Optional[str] = None
        self._order_desc: bool = False
        self._range: Optional[tuple[int, int]] = None
        self._count_mode: Optional[str] = None
        self._single: bool = False

    def _rows(self) -> List[Dict[str, Any]]:
        return self.client.tables.setdefault(self.name, [])

    def select(self, *_args, **kwargs) -> "FakeQuery":
        self._operation = "select"
        self._count_mode = kwargs.get("count")
        return self

    def insert(self, payload: Any) -> "FakeQuery":
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]) -> "FakeQuery":
        self._operation = "update"
        self._payload = payload
        return self

    def delete(self) -> "FakeQuery":
        self._operation = "delete"
        return self

    def eq(self, field: str, value: Any) -> "FakeQuery":
        self._predicates.append(lambda row: row.get(field) == value)
        return self

    def in_(self, field: str, values: Iterable[Any]) -> "FakeQuery":
        value_set = set(values)
        self._predicates.append(lambda row: row.get(field) in value_set)
        return self

    def lte(self, field: str, value: Any) -> "FakeQuery":
        self._predicates.append(lambda row: row.get(field) is not None and row.get(field) <= value)
        return self

    def is_(self, field: str, value: Any) -> "FakeQuery":
        if value == "null":
            self._predicates.append(lambda row: row.get(field) is None)
        else:
            self._predicates.append(lambda row: row.get(field) == value)
        return self

    def not_(self, field: str, operator: str, value: Any) -> "FakeQuery":
        if operator == "is" and (value is None or value == "null"):
            self._predicates.append(lambda row: row.get(field) is not None)
        elif operator == "eq":
            self._predicates.append(lambda row: row.get(field) != value)
        else:  # pragma: no cover - defensive for unsupported operators in tests
            raise NotImplementedError(f"Unsupported not_ operator: {operator}")
        return self

    def order(self, field: str, desc: bool = False) -> "FakeQuery":
        self._order_field = field
        self._order_desc = desc
        return self

    def range(self, start: int, end: int) -> "FakeQuery":
        self._range = (start, end)
        return self

    def single(self) -> "FakeQuery":
        self._single = True
        return self

    def execute(self):
        rows = list(self._rows())

        if self._operation == "insert":
            payloads = payload_list(self._payload)
            inserted: List[Dict[str, Any]] = []
            for item in payloads:
                new_row = dict(item)
                if "id" not in new_row:
                    new_row["id"] = f"auto-{len(self.client.tables[self.name]) + len(inserted) + 1}"
                self.client.tables[self.name].append(new_row)
                inserted.append(dict(new_row))
            return SimpleNamespace(data=inserted)

        if self._operation == "update":
            updated_rows = []
            for row in rows:
                if all(pred(row) for pred in self._predicates):
                    row.update(self._payload)
                    updated_rows.append(dict(row))
            return SimpleNamespace(data=updated_rows)

        if self._operation == "delete":
            remaining = []
            removed = []
            for row in rows:
                if all(pred(row) for pred in self._predicates):
                    removed.append(row)
                else:
                    remaining.append(row)
            self.client.tables[self.name] = remaining
            return SimpleNamespace(data=removed)

        # select
        filtered = [row for row in rows if all(pred(row) for pred in self._predicates)]

        if self._order_field:
            filtered.sort(key=lambda row: row.get(self._order_field), reverse=self._order_desc)

        if self._range:
            start, end = self._range
            filtered = filtered[start : end + 1]

        count = len(filtered) if self._count_mode == "exact" else None

        if self._single:
            data = filtered[0] if filtered else None
            return SimpleNamespace(data=data, count=count)

        return SimpleNamespace(data=filtered, count=count)


class FakeSupabase:
    def __init__(self, tables: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = tables or {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def payload_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    return [payload]


@pytest.fixture(autouse=True)
def _patch_supabase(monkeypatch):
    tables = {
        "users": [
            {"id": "seller-1", "user_type": "seller", "email": "seller1@example.com"},
            {"id": "seller-2", "user_type": "seller", "email": "seller2@example.com"},
        ]
    }
    stub = FakeSupabase(tables)
    monkeypatch.setattr(message_service, "get_supabase", lambda: stub)
    yield


def build_app() -> TestClient:
    app = FastAPI()
    app.include_router(admin_messages.router, prefix="/api")
    app.include_router(operator_messages.router, prefix="/api")
    return TestClient(app)

def test_create_and_dispatch_message():
    payload = OperatorMessageCreateRequest(title="テスト", body_text="本文", send_now=True)
    message = message_service.create_message(payload, actor_id="admin-1")
    assert message.status == "sent"
    assert message.send_email is False

    stub = message_service.get_supabase()
    recipients = stub.tables.get("operator_message_recipients", [])
    assert recipients, "expected recipients to be created"
    direct = stub.table("operator_message_recipients").select("*").eq("user_id", "seller-1").execute()
    assert direct.data, "direct query should return recipient"

    inbox = message_service.list_user_inbox(user_id="seller-1", limit=20, offset=0)
    assert inbox["data"], inbox
    assert inbox["total"] == 1
    assert inbox["data"][0]["title"] == "テスト"


def test_dispatch_message_with_email_sends_mail(monkeypatch):
    sent_payload = {}

    def fake_send_bulk_email_async(**kwargs):
        sent_payload.update(kwargs)
        return [recipient.email for recipient in kwargs["recipients"]]

    monkeypatch.setattr(message_service.mailgun, "send_bulk_email_async", fake_send_bulk_email_async)

    # Configure Mailgun defaults
    monkeypatch.setattr(message_service.settings, "mailgun_api_key", "test-key", raising=False)
    monkeypatch.setattr(message_service.settings, "mailgun_domain", "mg.example.com", raising=False)
    monkeypatch.setattr(message_service.settings, "mailgun_default_from_email", "no-reply@example.com", raising=False)
    monkeypatch.setattr(message_service.settings, "mailgun_default_from_name", "D-swipe", raising=False)
    monkeypatch.setattr(message_service.settings, "mailgun_default_reply_to", "support@example.com", raising=False)

    payload = OperatorMessageCreateRequest(
        title="メール配信",
        body_text="本文",
        send_now=True,
        send_email=True,
        email_subject="メール件名",
    )
    message_service.create_message(payload, actor_id="admin-1")

    assert "recipients" in sent_payload
    assert sent_payload["subject"] == "メール件名"
    assert sent_payload["sender_email"] == "no-reply@example.com"
    assert sent_payload["reply_to"] == "support@example.com"
    assert len(sent_payload["recipients"]) == 2

    stub = message_service.get_supabase()
    for row in stub.tables.get("operator_message_recipients", []):
        if row.get("message_id"):
            assert row.get("email_sent_at"), "email_sent_at should be recorded"


def test_mark_message_read(monkeypatch):
    stub = message_service.get_supabase()
    message_id = "msg-1"
    stub.tables.setdefault("operator_messages", []).append({
        "id": message_id,
        "title": "お知らせ",
        "body_text": "内容",
        "category": "general",
        "priority": "normal",
        "status": "sent",
        "send_at": "2025-01-01T00:00:00+00:00",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    })
    stub.tables.setdefault("operator_message_recipients", []).append({
        "id": "rec-1",
        "message_id": message_id,
        "user_id": "seller-1",
        "delivery_status": "delivered",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "read_at": None,
        "archived": False,
    })

    client = build_app()
    monkeypatch.setattr(operator_messages, "_get_current_user", lambda credentials: {"id": "seller-1"})

    token = create_fake_token("seller-1")
    resp = client.post(
        f"/api/messages/{message_id}/read",
        json={"read": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    recipient_row = stub.tables["operator_message_recipients"][0]
    assert recipient_row["read_at"] is not None


def create_fake_token(user_id: str) -> str:
    # In tests we bypass actual JWT: routes patch _get_current_user, so token value doesn't matter.
    return f"token-for-{user_id}"


def test_create_message_with_email_targets():
    payload = OperatorMessageCreateRequest(
        title="メールターゲット",
        body_text="本文",
        send_now=True,
        target_segments=[
            OperatorMessageSegment(segment_type="emails", segment_payload={"emails": ["seller1@example.com"]}),
        ],
    )
    message = message_service.create_message(payload, actor_id="admin-1")
    assert message.status == "sent"

    stub = message_service.get_supabase()
    recipients = stub.tables.get("operator_message_recipients", [])
    assert len(recipients) == 1
    assert recipients[0]["user_id"] == "seller-1"


def test_create_message_with_unknown_email():
    payload = OperatorMessageCreateRequest(
        title="未登録メール",
        body_text="本文",
        send_now=True,
        target_segments=[
            OperatorMessageSegment(segment_type="emails", segment_payload={"emails": ["unknown@example.com"]}),
        ],
    )
    with pytest.raises(message_service.SegmentResolutionError) as exc:
        message_service.create_message(payload, actor_id="admin-1")

    assert exc.value.missing_emails == ["unknown@example.com"]
    assert exc.value.args[0] == "segment_email_not_found"


def test_create_message_with_empty_email_segment():
    payload = OperatorMessageCreateRequest(
        title="空メール",
        body_text="本文",
        send_now=True,
        target_segments=[
            OperatorMessageSegment(segment_type="emails", segment_payload={"emails": []}),
        ],
    )
    with pytest.raises(message_service.SegmentResolutionError) as exc:
        message_service.create_message(payload, actor_id="admin-1")

    assert exc.value.args[0] == "segment_email_empty"


def test_list_visibility_filters():
    payload = OperatorMessageCreateRequest(title="list test", body_text="body", send_now=True)
    message = message_service.create_message(payload, actor_id="admin-1")

    message_service.set_hidden(message.id, hidden=True)
    hidden = message_service.list_messages(visibility="hidden")
    assert hidden["total"] == 1
    assert hidden["data"][0].id == message.id

    message_service.set_hidden(message.id, hidden=False)
    message_service.set_archived(message.id, archived=True)
    archived = message_service.list_messages(visibility="archived")
    assert archived["total"] == 1
    assert archived["data"][0].id == message.id

    with pytest.raises(ValueError):
        message_service.list_messages(visibility="invalid")


def test_list_messages_excludes_automated_by_default():
    manual = message_service.create_message(
        OperatorMessageCreateRequest(title="manual", body_text="body", send_now=True),
        actor_id="admin-1",
    )
    automated = message_service.create_message(
        OperatorMessageCreateRequest(title="auto", body_text="body", send_now=True, automated=True),
        actor_id="automation",
    )

    default_list = message_service.list_messages(visibility="all")
    ids = [msg.id for msg in default_list["data"]]
    assert manual.id in ids
    assert automated.id not in ids

    include_auto = message_service.list_messages(visibility="all", include_automated=True)
    ids_with_auto = [msg.id for msg in include_auto["data"]]
    assert manual.id in ids_with_auto
    assert automated.id in ids_with_auto


def test_hide_toggle_message():
    payload = OperatorMessageCreateRequest(title="hide", body_text="body", send_now=True)
    message = message_service.create_message(payload, actor_id="admin-1")

    hidden = message_service.set_hidden(message.id, hidden=True)
    assert hidden.admin_hidden is True

    visible = message_service.set_hidden(message.id, hidden=False)
    assert visible.admin_hidden is False


def test_archive_toggle_message():
    payload = OperatorMessageCreateRequest(title="archive", body_text="body", send_now=True)
    message = message_service.create_message(payload, actor_id="admin-1")

    archived = message_service.set_archived(message.id, archived=True)
    assert archived.admin_archived_at is not None

    unarchived = message_service.set_archived(message.id, archived=False)
    assert unarchived.admin_archived_at is None


def test_delete_message():
    payload = OperatorMessageCreateRequest(title="delete", body_text="body", send_now=True)
    message = message_service.create_message(payload, actor_id="admin-1")

    message_service.delete_message(message.id)

    stub = message_service.get_supabase()
    assert not any(row.get("id") == message.id for row in stub.tables.get("operator_messages", []))
    assert not any(row.get("message_id") == message.id for row in stub.tables.get("operator_message_segments", []))
    assert not any(row.get("message_id") == message.id for row in stub.tables.get("operator_message_recipients", []))
