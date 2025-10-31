from copy import deepcopy
import os
import sys
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.routes import salon_assets
from app.models.salon_roles import SalonRolePermissions


class _Response:
    def __init__(self, data=None, count: Optional[int] = None):
        self.data = data
        self.count = count


class FakeSupabase:
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
        self._single: bool = False
        self._operation: str = "select"
        self._payload: Any = None
        self._count_mode: Optional[str] = None

    @property
    def _table(self) -> List[Dict[str, Any]]:
        return self.client.tables[self.name]

    def _matching_rows(self) -> List[Dict[str, Any]]:
        matches = []
        for row in self._table:
            matched = True
            for op, field, value in self._filters:
                current = row.get(field)
                if op == "eq" and current != value:
                    matched = False
                    break
            if matched:
                matches.append(row)
        return matches

    def select(self, *_: Any, **kwargs: Any):
        self._operation = "select"
        self._count_mode = kwargs.get("count")
        return self

    def eq(self, field: str, value: Any):
        self._filters.append(("eq", field, value))
        return self

    def single(self):
        self._single = True
        return self

    def order(self, field: str, desc: bool = False):
        self._order_field = field
        self._order_desc = desc
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
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
            record.setdefault("created_at", "2024-01-01T00:00:00Z")
            record.setdefault("updated_at", "2024-01-01T00:00:00Z")
            self._table.append(record)
            return _Response(data=[deepcopy(record)])

        if self._operation == "update":
            updated: List[Dict[str, Any]] = []
            for row in self._matching_rows():
                row.update(self._payload)
                row.setdefault("updated_at", "2024-01-02T00:00:00Z")
                updated.append(deepcopy(row))
            return _Response(data=updated)

        if self._operation == "delete":
            targets = set(id(row) for row in self._matching_rows())
            self.client.tables[self.name] = [row for row in self._table if id(row) not in targets]
            return _Response(data=[])

        rows = [deepcopy(row) for row in self._matching_rows()]

        if self._order_field:
            rows.sort(key=lambda item: item.get(self._order_field), reverse=self._order_desc)

        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]

        if self._single:
            return _Response(data=rows[0] if rows else None)

        count = len(self._matching_rows()) if self._count_mode == "exact" else None
        return _Response(data=rows, count=count)


def _patch_permissions(monkeypatch, user_id: str, owner_id: str, allow_manage: bool = True):
    monkeypatch.setattr(salon_assets, "_get_current_user", lambda _: {"id": user_id, "username": "user"})
    monkeypatch.setattr(
        salon_assets,
        "_get_salon_and_access",
        lambda client, salon_id, _: ({"id": salon_id, "owner_id": owner_id}, allow_manage),
    )
    monkeypatch.setattr(
        salon_assets,
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


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(salon_assets.router, prefix="/api")
    return TestClient(app)


@pytest.mark.asyncio
async def test_list_assets_returns_records(monkeypatch, app_client):
    fake_supabase = FakeSupabase(
        {
            "salon_assets": [
                {
                    "id": "asset-1",
                    "salon_id": "salon-1",
                    "uploader_id": "owner-1",
                    "asset_type": "IMAGE",
                    "title": "Welcome Poster",
                    "description": None,
                    "file_url": "https://example.com/a.png",
                    "thumbnail_url": None,
                    "content_type": "image/png",
                    "file_size": 12345,
                    "visibility": "MEMBERS",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                },
                {
                    "id": "asset-2",
                    "salon_id": "salon-1",
                    "uploader_id": "owner-1",
                    "asset_type": "VIDEO",
                    "title": "Promo",
                    "description": "Intro video",
                    "file_url": "https://example.com/b.mp4",
                    "thumbnail_url": None,
                    "content_type": "video/mp4",
                    "file_size": 67890,
                    "visibility": "PUBLIC",
                    "created_at": "2024-01-02T00:00:00Z",
                    "updated_at": "2024-01-02T00:00:00Z",
                },
            ]
        }
    )

    monkeypatch.setattr(salon_assets, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "member-1", "owner-1", allow_manage=False)

    response = app_client.get(
        "/api/salons/salon-1/assets",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["data"]) == 2
    assert payload["data"][0]["id"] == "asset-2"  # newest first


@pytest.mark.asyncio
async def test_upload_asset_stores_metadata(monkeypatch, app_client):
    fake_supabase = FakeSupabase({"salon_assets": []})
    uploaded_files: List[Dict[str, Any]] = []

    def fake_upload(*, file_content: bytes, file_name: str, content_type: str, folder: str) -> str:
        uploaded_files.append({
            "len": len(file_content),
            "name": file_name,
            "type": content_type,
            "folder": folder,
        })
        return f"https://cdn.example.com/{uuid4()}"

    monkeypatch.setattr(salon_assets, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "owner-1", "owner-1", allow_manage=True)
    monkeypatch.setattr(salon_assets.storage, "upload_file", fake_upload)

    response = app_client.post(
        "/api/salons/salon-1/assets",
        headers={"Authorization": "Bearer token"},
        data={
            "title": "Guide",
            "description": "PDF guide",
            "visibility": "PUBLIC",
        },
        files={
            "file": ("guide.pdf", b"dummy", "application/pdf"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Guide"
    assert payload["asset_type"] == "DOCUMENT"
    assert uploaded_files[0]["folder"] == "salons/salon-1/assets"


@pytest.mark.asyncio
async def test_delete_asset_removes_record(monkeypatch, app_client):
    asset_record = {
        "id": "asset-del",
        "salon_id": "salon-1",
        "uploader_id": "owner-1",
        "asset_type": "IMAGE",
        "title": "Temp",
        "description": None,
        "file_url": "https://cdn.example.com/temp.png",
        "thumbnail_url": None,
        "content_type": "image/png",
        "file_size": 100,
        "visibility": "MEMBERS",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    fake_supabase = FakeSupabase({"salon_assets": [asset_record]})
    delete_calls: List[str] = []

    monkeypatch.setattr(salon_assets, "get_supabase_client", lambda: fake_supabase)
    _patch_permissions(monkeypatch, "owner-1", "owner-1", allow_manage=True)
    monkeypatch.setattr(salon_assets.storage, "delete_file", lambda url: delete_calls.append(url))

    response = app_client.delete(
        "/api/salons/salon-1/assets/asset-del",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 204
    assert delete_calls == ["https://cdn.example.com/temp.png"]
    assert fake_supabase.tables["salon_assets"] == []
