"""Salon announcements endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salon_announcements import (
    SalonAnnouncementCreateRequest,
    SalonAnnouncementListResponse,
    SalonAnnouncementResponse,
    SalonAnnouncementUpdateRequest,
)
from app.routes.salon_events import _get_salon_and_access  # reuse membership helper
from app.utils.auth import decode_access_token
from app.utils.salon_permissions import ensure_permission, get_user_permissions


router = APIRouter(prefix="/salons/{salon_id}/announcements", tags=["salon-announcements"])
security = HTTPBearer()


def _get_current_user(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

    supabase = get_supabase_client()
    response = (
        supabase
        .table("users")
        .select("id, username, user_type")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")
    return response.data


def _map_record(record: Dict[str, Any]) -> SalonAnnouncementResponse:
    return SalonAnnouncementResponse(
        id=record.get("id"),
        salon_id=record.get("salon_id"),
        author_id=record.get("author_id"),
        title=record.get("title", ""),
        body=record.get("body", ""),
        is_pinned=bool(record.get("is_pinned", False)),
        is_published=bool(record.get("is_published", True)),
        start_at=record.get("start_at"),
        end_at=record.get("end_at"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


def _validate_schedule(start_at: Optional[datetime], end_at: Optional[datetime]) -> None:
    if start_at and end_at and end_at < start_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="終了日時は開始日時より後に設定してください")


def _is_active(record: Dict[str, Any], now: datetime) -> bool:
    if not record.get("is_published", True):
        return False
    start_at = record.get("start_at")
    end_at = record.get("end_at")
    if start_at:
        if isinstance(start_at, str):
            start_at = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
        if start_at and start_at > now:
            return False
    if end_at:
        if isinstance(end_at, str):
            end_at = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
        if end_at and end_at < now:
            return False
    return True


@router.get("", response_model=SalonAnnouncementListResponse)
async def list_announcements(
    salon_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_unpublished: bool = Query(False, description="未公開のお知らせを含める (管理者のみ)"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    can_manage = is_owner or permissions.manage_announcements

    query = supabase.table("salon_announcements").select("*").eq("salon_id", salon_id)
    if not can_manage or not include_unpublished:
        query = query.eq("is_published", True)

    count_query = supabase.table("salon_announcements").select("id", count="exact").eq("salon_id", salon_id)
    if not can_manage or not include_unpublished:
        count_query = count_query.eq("is_published", True)

    count_resp = count_query.execute()
    total = getattr(count_resp, "count", 0) or 0

    range_end = offset + limit - 1
    data_resp = (
        query
        .order("is_pinned", desc=True)
        .order("start_at", desc=True)
        .order("created_at", desc=True)
        .range(offset, range_end)
        .execute()
    )
    records = data_resp.data or []

    now = datetime.now(timezone.utc)
    if not can_manage or not include_unpublished:
        records = [record for record in records if _is_active(record, now)]
        total = len(records)

    data = [_map_record(record) for record in records]
    return SalonAnnouncementListResponse(data=data, total=total, limit=limit, offset=offset)


@router.post("", response_model=SalonAnnouncementResponse, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    salon_id: str,
    payload: SalonAnnouncementCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_announcements", "お知らせを作成する権限がありません")

    _validate_schedule(payload.start_at, payload.end_at)

    announcement = {
        "salon_id": salon_id,
        "author_id": user["id"],
        "title": payload.title,
        "body": payload.body,
        "is_pinned": payload.is_pinned,
        "is_published": payload.is_published,
        "start_at": payload.start_at.isoformat() if payload.start_at else None,
        "end_at": payload.end_at.isoformat() if payload.end_at else None,
    }

    response = supabase.table("salon_announcements").insert(announcement).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="お知らせの作成に失敗しました")

    record = response.data[0]
    return _map_record(record)


@router.patch("/{announcement_id}", response_model=SalonAnnouncementResponse)
async def update_announcement(
    salon_id: str,
    announcement_id: str,
    payload: SalonAnnouncementUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_announcements", "お知らせを更新する権限がありません")

    existing_resp = (
        supabase
        .table("salon_announcements")
        .select("*")
        .eq("id", announcement_id)
        .eq("salon_id", salon_id)
        .single()
        .execute()
    )
    record = existing_resp.data
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="お知らせが見つかりません")

    start_at = payload.start_at if payload.start_at is not None else record.get("start_at")
    end_at = payload.end_at if payload.end_at is not None else record.get("end_at")
    if isinstance(start_at, str):
        start_at = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    if isinstance(end_at, str):
        end_at = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    _validate_schedule(start_at, end_at)

    updates: Dict[str, Any] = {}
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.body is not None:
        updates["body"] = payload.body
    if payload.is_pinned is not None:
        updates["is_pinned"] = payload.is_pinned
    if payload.is_published is not None:
        updates["is_published"] = payload.is_published
    if payload.start_at is not None:
        updates["start_at"] = payload.start_at.isoformat() if payload.start_at else None
    if payload.end_at is not None:
        updates["end_at"] = payload.end_at.isoformat() if payload.end_at else None

    if not updates:
        return _map_record(record)

    update_resp = (
        supabase
        .table("salon_announcements")
        .update(updates)
        .eq("id", announcement_id)
        .eq("salon_id", salon_id)
        .execute()
    )
    if not update_resp.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="お知らせの更新に失敗しました")

    return _map_record(update_resp.data[0])


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    salon_id: str,
    announcement_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_announcements", "お知らせを削除する権限がありません")

    supabase.table("salon_announcements").delete().eq("id", announcement_id).eq("salon_id", salon_id).execute()
    return None
