from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import purchase_notifications


class StubTable:
    def __init__(self, parent, name: str):
        self.parent = parent
        self.name = name
        self._filters = []
        self._select_cols = None
        self._single = False
        self._payload = None

    def select(self, columns: str):
        self._select_cols = columns
        return self

    def eq(self, field: str, value):
        self._filters.append((field, value))
        return self

    def maybe_single(self):
        self._single = True
        return self

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        if self.name == "users":
            rows = [row for row in self.parent.users if all(row.get(field) == value for field, value in self._filters)]
            data = rows[0] if rows else None
            return SimpleNamespace(data=data)

        if self.name == "operator_messages":
            payload = dict(self._payload)
            payload.setdefault("id", f"msg-{len(self.parent.operator_messages) + 1}")
            self.parent.operator_messages.append(payload)
            return SimpleNamespace(data=[payload])

        if self.name == "operator_message_recipients":
            payload = dict(self._payload)
            self.parent.operator_message_recipients.append(payload)
            return SimpleNamespace(data=[payload])

        raise NotImplementedError(f"Unhandled table {self.name}")


class StubSupabase:
    def __init__(self):
        self.users = []
        self.operator_messages = []
        self.operator_message_recipients = []

    def table(self, name: str):
        return StubTable(self, name)


@pytest.fixture()
def stub_supabase():
    supabase = StubSupabase()
    supabase.users.extend(
        [
            {
                "id": "buyer-1",
                "email": "buyer@example.com",
                "display_name": "Buyer One",
                "username": "buyer1",
            },
            {
                "id": "seller-1",
                "email": "seller@example.com",
                "display_name": "Seller One",
                "username": "seller1",
            },
        ]
    )
    return supabase


def test_purchase_notification_sends_email(monkeypatch, stub_supabase):
    captured = {}

    def fake_send_bulk_email_async(**kwargs):
        captured.update(kwargs)
        return [recipient.email for recipient in kwargs["recipients"]]

    monkeypatch.setattr(purchase_notifications.mailgun, "send_bulk_email_async", fake_send_bulk_email_async)
    monkeypatch.setattr(purchase_notifications.mailgun, "is_configured", lambda: True)
    monkeypatch.setattr(purchase_notifications.settings, "mailgun_default_from_email", "no-reply@example.com")
    monkeypatch.setattr(purchase_notifications.settings, "mailgun_default_from_name", "D-swipe")
    monkeypatch.setattr(purchase_notifications.settings, "mailgun_default_reply_to", "support@example.com")

    purchase_notifications.send_purchase_notification(
        stub_supabase,
        buyer_id="buyer-1",
        content_title="テスト商品",
        content_type="note",
        seller_id="seller-1",
        amount_jpy=1200,
        points=None,
        quantity=1,
    )

    assert stub_supabase.operator_messages, "operator message should be created"
    assert stub_supabase.operator_message_recipients, "recipient record should be created"
    assert captured["subject"].startswith("ご購入ありがとうございます")
    assert captured["recipients"][0].email == "buyer@example.com"


def test_purchase_notification_skips_email_when_unconfigured(monkeypatch, stub_supabase):
    sent = {}

    def fake_send_bulk_email_async(**kwargs):
        sent.update(kwargs)
        return []

    monkeypatch.setattr(purchase_notifications.mailgun, "send_bulk_email_async", fake_send_bulk_email_async)
    monkeypatch.setattr(purchase_notifications.mailgun, "is_configured", lambda: False)
    monkeypatch.setattr(purchase_notifications.settings, "mailgun_default_from_email", "no-reply@example.com")
    monkeypatch.setattr(purchase_notifications.settings, "mailgun_default_from_name", "D-swipe")
    monkeypatch.setattr(purchase_notifications.settings, "mailgun_default_reply_to", "support@example.com")

    purchase_notifications.send_purchase_notification(
        stub_supabase,
        buyer_id="buyer-1",
        content_title="テスト商品",
        content_type="note",
    )

    assert "subject" not in sent
