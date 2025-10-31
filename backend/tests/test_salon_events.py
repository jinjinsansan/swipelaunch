import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.models.salon_events import SalonEventAttendRequest, SalonEventCreateRequest
from app.routes import salon_events
from app.models.salon_roles import SalonRolePermissions


class _Response(SimpleNamespace):
    """Simple response object that mimics Supabase execute return."""


class FakeSupabase:
    """Minimal in-memory Supabase stub for salon events tests."""

    def __init__(self, initial_tables: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        if initial_tables:
            for name, rows in initial_tables.items():
                self.tables[name] = [deepcopy(row) for row in rows]

    def table(self, name: str):
        if name not in self.tables:
            self.tables[name] = []
        return _Table(self, name)


class _Table:
    def __init__(self, client: FakeSupabase, name: str) -> None:
        self.client = client
        self.name = name
        self._filters: List[tuple[str, str, Any]] = []
        self._order_field: Optional[str] = None
        self._order_desc: bool = False
        self._range: Optional[tuple[int, int]] = None
        self._limit: Optional[int] = None
        self._single: bool = False
        self._operation: str = "select"
        self._payload: Any = None
        self._count_mode: Optional[str] = None

    @property
    def _table(self) -> List[Dict[str, Any]]:
        return self.client.tables[self.name]

    def _matching_rows(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for row in self._table:
            matched = True
            for op, field, value in self._filters:
                current = row.get(field)
                if op == "eq" and current != value:
                    matched = False
                    break
                if op == "in" and current not in value:
                    matched = False
                    break
            if matched:
                results.append(row)
        return results

    def select(self, *_: Any, **kwargs: Any):
        self._operation = "select"
        self._count_mode = kwargs.get("count")
        return self

    def eq(self, field: str, value: Any):
        self._filters.append(("eq", field, value))
        return self

    def in_(self, field: str, values: Iterable[Any]):
        self._filters.append(("in", field, list(values)))
        return self

    def order(self, field: str, desc: bool = False):
        self._order_field = field
        self._order_desc = desc
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, payload: Dict[str, Any]):
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        return self

    def delete(self):
        self._operation = "delete"
        return self

    def execute(self):
        if self._operation == "insert":
            record = deepcopy(self._payload)
            record.setdefault("id", str(uuid4()))
            now = datetime.now(timezone.utc).isoformat()
            record.setdefault("created_at", now)
            record.setdefault("updated_at", now)
            self._table.append(record)
            return _Response(data=[deepcopy(record)])

        if self._operation == "update":
            updated: List[Dict[str, Any]] = []
            for row in self._matching_rows():
                row.update(self._payload)
                row.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
                updated.append(deepcopy(row))
            return _Response(data=updated)

        if self._operation == "delete":
            remaining = []
            to_remove = set(id(row) for row in self._matching_rows())
            for row in self._table:
                if id(row) not in to_remove:
                    remaining.append(row)
            self.client.tables[self.name] = remaining
            return _Response(data=[])

        rows = [deepcopy(row) for row in self._matching_rows()]

        if self._order_field:
            rows.sort(key=lambda item: item.get(self._order_field), reverse=self._order_desc)

        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]

        if self._limit is not None:
            rows = rows[: self._limit]

        if self._single:
            return _Response(data=rows[0] if rows else None)

        response = _Response(data=rows)
        if self._count_mode == "exact":
            response.count = len(self._matching_rows())
        return response


def _auth_credentials() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="dummy")


def _patch_auth(monkeypatch, user_id: str, owner_id: str, allow_manage: bool = True):
    monkeypatch.setattr(salon_events, "_get_current_user", lambda _: {"id": user_id, "username": "owner"})
    monkeypatch.setattr(
        salon_events,
        "_get_salon_and_access",
        lambda client, salon_id, _: ({"id": salon_id, "owner_id": owner_id}, allow_manage),
    )
    monkeypatch.setattr(
        salon_events,
        "get_user_permissions",
        lambda client, salon_id, _, *, is_owner: SalonRolePermissions(
            manage_feed=True,
            manage_events=True,
            manage_assets=True,
            manage_announcements=True,
            manage_members=True,
            manage_roles=True,
        )
        if is_owner
        else SalonRolePermissions(
            manage_feed=allow_manage,
            manage_events=allow_manage,
            manage_assets=allow_manage,
            manage_announcements=allow_manage,
            manage_members=allow_manage,
            manage_roles=allow_manage,
        ),
    )


@pytest.mark.asyncio
async def test_list_events_returns_attendee_counts(monkeypatch):
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    later = start + timedelta(hours=2)

    fake_supabase = FakeSupabase(
        {
            "salon_events": [
                {
                    "id": "event-1",
                    "salon_id": "salon-123",
                    "organizer_id": "owner-123",
                    "title": "Monthly Meetup",
                    "description": "Discuss updates",
                    "start_at": start.isoformat(),
                    "end_at": later.isoformat(),
                    "location": "Tokyo",
                    "meeting_url": None,
                    "is_public": True,
                    "capacity": 50,
                    "created_at": start.isoformat(),
                    "updated_at": start.isoformat(),
                },
                {
                    "id": "event-2",
                    "salon_id": "salon-123",
                    "organizer_id": "owner-123",
                    "title": "Workshop",
                    "description": None,
                    "start_at": (start + timedelta(days=1)).isoformat(),
                    "end_at": None,
                    "location": "Online",
                    "meeting_url": "https://example.com",
                    "is_public": False,
                    "capacity": None,
                    "created_at": start.isoformat(),
                    "updated_at": start.isoformat(),
                },
            ],
            "salon_event_attendees": [
                {"id": "att-1", "event_id": "event-1", "user_id": "user-a", "status": "GOING"},
                {"id": "att-2", "event_id": "event-1", "user_id": "user-b", "status": "INTERESTED"},
                {"id": "att-3", "event_id": "event-2", "user_id": "owner-123", "status": "GOING"},
            ],
            "users": [
                {"id": "owner-123", "username": "owner123", "user_type": "OWNER"},
            ],
        }
    )

    monkeypatch.setattr(salon_events, "get_supabase_client", lambda: fake_supabase)
    _patch_auth(monkeypatch, user_id="owner-123", owner_id="owner-123")

    response = await salon_events.list_events(
        salon_id="salon-123",
        limit=20,
        offset=0,
        credentials=_auth_credentials(),
    )

    assert response.total == 2
    assert response.data[0].attendee_count == 2
    assert response.data[0].is_attending is False
    assert response.data[1].attendee_count == 1
    assert response.data[1].is_attending is True


@pytest.mark.asyncio
async def test_create_event_persists_record(monkeypatch):
    start = datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc)
    fake_supabase = FakeSupabase(
        {
            "salon_events": [],
            "salon_event_attendees": [],
        }
    )

    monkeypatch.setattr(salon_events, "get_supabase_client", lambda: fake_supabase)
    _patch_auth(monkeypatch, user_id="owner-123", owner_id="owner-123", allow_manage=True)

    payload = SalonEventCreateRequest(
        title="Strategy Session",
        description="Deep dive into roadmap",
        start_at=start,
        end_at=start + timedelta(hours=1),
        location="Zoom",
        meeting_url="https://zoom.example.com",
        is_public=False,
        capacity=25,
    )

    created = await salon_events.create_event(
        salon_id="salon-abc",
        payload=payload,
        credentials=_auth_credentials(),
    )

    assert created.title == "Strategy Session"
    assert created.organizer_id == "owner-123"
    assert created.capacity == 25

    stored_events = fake_supabase.tables["salon_events"]
    assert len(stored_events) == 1
    assert stored_events[0]["salon_id"] == "salon-abc"
    assert stored_events[0]["title"] == "Strategy Session"


@pytest.mark.asyncio
async def test_attend_event_respects_capacity(monkeypatch):
    start = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)
    fake_supabase = FakeSupabase(
        {
            "salon_events": [
                {
                    "id": "event-777",
                    "salon_id": "salon-xyz",
                    "organizer_id": "owner-xyz",
                    "title": "Morning Yoga",
                    "description": None,
                    "start_at": start.isoformat(),
                    "end_at": None,
                    "location": "Studio",
                    "meeting_url": None,
                    "is_public": True,
                    "capacity": 1,
                    "created_at": start.isoformat(),
                    "updated_at": start.isoformat(),
                }
            ],
            "salon_event_attendees": [
                {
                    "id": "att-existing",
                    "event_id": "event-777",
                    "user_id": "member-1",
                    "status": "GOING",
                    "note": None,
                    "created_at": start.isoformat(),
                    "updated_at": start.isoformat(),
                }
            ],
        }
    )

    monkeypatch.setattr(salon_events, "get_supabase_client", lambda: fake_supabase)
    _patch_auth(monkeypatch, user_id="member-2", owner_id="owner-xyz", allow_manage=False)

    with pytest.raises(HTTPException) as exc_info:
        await salon_events.attend_event(
            salon_id="salon-xyz",
            event_id="event-777",
            payload=SalonEventAttendRequest(status="GOING"),
            credentials=_auth_credentials(),
        )

    assert exc_info.value.status_code == 409
    assert "定員に達しています" in exc_info.value.detail
