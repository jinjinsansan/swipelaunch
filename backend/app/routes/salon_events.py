"""Salon event management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salon_events import (
    SalonEventAttendRequest,
    SalonEventAttendeeListResponse,
    SalonEventAttendeeResponse,
    SalonEventCreateRequest,
    SalonEventListResponse,
    SalonEventResponse,
    SalonEventUpdateRequest,
)
from app.utils.auth import decode_access_token
from app.utils.salon_permissions import ensure_permission, get_user_permissions


router = APIRouter(prefix="/salons/{salon_id}/events", tags=["salon-events"])
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


def _get_salon_and_access(supabase, salon_id: str, user_id: str) -> Tuple[Dict[str, Any], bool]:
    salon_response = (
        supabase
        .table("salons")
        .select("id, owner_id")
        .eq("id", salon_id)
        .single()
        .execute()
    )
    if not salon_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")

    salon = salon_response.data
    if salon.get("owner_id") == user_id:
        return salon, True

    membership_response = (
        supabase
        .table("salon_memberships")
        .select("status")
        .eq("salon_id", salon_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    for membership in membership_response.data or []:
        if str(membership.get("status", "")).upper() == "ACTIVE":
            return salon, False

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="このサロンにアクセスする権限がありません")


def _map_event_record(
    record: Dict[str, Any],
    attendee_count: int,
    is_attending: bool,
) -> SalonEventResponse:
    return SalonEventResponse(
        id=record.get("id"),
        salon_id=record.get("salon_id"),
        organizer_id=record.get("organizer_id"),
        title=record.get("title"),
        description=record.get("description"),
        start_at=record.get("start_at"),
        end_at=record.get("end_at"),
        location=record.get("location"),
        meeting_url=record.get("meeting_url"),
        is_public=bool(record.get("is_public", True)),
        capacity=record.get("capacity"),
        attendee_count=attendee_count,
        is_attending=is_attending,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


def _map_attendee_record(record: Dict[str, Any], username: str | None) -> SalonEventAttendeeResponse:
    return SalonEventAttendeeResponse(
        id=record.get("id"),
        event_id=record.get("event_id"),
        user_id=record.get("user_id"),
        status=record.get("status", "GOING"),
        note=record.get("note"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        username=username,
    )


def _fetch_event(supabase, salon_id: str, event_id: str) -> Dict[str, Any]:
    response = (
        supabase
        .table("salon_events")
        .select("*")
        .eq("id", event_id)
        .eq("salon_id", salon_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="イベントが見つかりません")
    return response.data


def _validate_event_dates(start_at: datetime, end_at: datetime | None) -> None:
    if end_at and end_at < start_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="終了日時は開始日時より後に設定してください")


def _get_attendee_stats(supabase, event_ids: List[str], user_id: str) -> Tuple[Dict[str, int], Dict[str, bool]]:
    attendee_counts: Dict[str, int] = {}
    attending_map: Dict[str, bool] = {}

    if not event_ids:
        return attendee_counts, attending_map

    counts_resp = (
        supabase
        .table("salon_event_attendees")
        .select("event_id")
        .in_("event_id", event_ids)
        .execute()
    )
    for row in counts_resp.data or []:
        event_id = row.get("event_id")
        if event_id:
            attendee_counts[event_id] = attendee_counts.get(event_id, 0) + 1

    attending_resp = (
        supabase
        .table("salon_event_attendees")
        .select("event_id")
        .eq("user_id", user_id)
        .in_("event_id", event_ids)
        .execute()
    )
    for row in attending_resp.data or []:
        event_id = row.get("event_id")
        if event_id:
            attending_map[event_id] = True

    return attendee_counts, attending_map


@router.get("", response_model=SalonEventListResponse)
async def list_events(
    salon_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, _ = _get_salon_and_access(supabase, salon_id, user["id"])

    count_resp = (
        supabase
        .table("salon_events")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
        .execute()
    )
    total = getattr(count_resp, "count", 0) or 0

    range_end = offset + limit - 1
    events_resp = (
        supabase
        .table("salon_events")
        .select("*")
        .eq("salon_id", salon_id)
        .order("start_at", asc=True)
        .range(offset, range_end)
        .execute()
    )
    records = events_resp.data or []
    event_ids = [record.get("id") for record in records if record.get("id")]

    attendee_counts, attending_map = _get_attendee_stats(supabase, event_ids, user["id"])

    data = [
        _map_event_record(
            record,
            attendee_counts.get(record.get("id"), 0),
            attending_map.get(record.get("id"), False),
        )
        for record in records
    ]

    return SalonEventListResponse(data=data, total=total, limit=limit, offset=offset)


@router.post("", response_model=SalonEventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    salon_id: str,
    payload: SalonEventCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_events", "イベントを作成する権限がありません")

    _validate_event_dates(payload.start_at, payload.end_at)

    event_data = {
        "salon_id": salon_id,
        "organizer_id": user["id"],
        "title": payload.title,
        "description": payload.description,
        "start_at": payload.start_at.isoformat(),
        "end_at": payload.end_at.isoformat() if payload.end_at else None,
        "location": payload.location,
        "meeting_url": payload.meeting_url,
        "is_public": payload.is_public,
        "capacity": payload.capacity,
    }

    response = supabase.table("salon_events").insert(event_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="イベントの作成に失敗しました")

    record = response.data[0]
    attendee_counts, attending_map = _get_attendee_stats(supabase, [record.get("id")], user["id"])
    return _map_event_record(
        record,
        attendee_counts.get(record.get("id"), 0),
        attending_map.get(record.get("id"), False),
    )


@router.get("/{event_id}", response_model=SalonEventResponse)
async def get_event(
    salon_id: str,
    event_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])

    record = _fetch_event(supabase, salon_id, event_id)
    attendee_counts, attending_map = _get_attendee_stats(supabase, [event_id], user["id"])
    return _map_event_record(
        record,
        attendee_counts.get(event_id, 0),
        attending_map.get(event_id, False),
    )


@router.patch("/{event_id}", response_model=SalonEventResponse)
async def update_event(
    salon_id: str,
    event_id: str,
    payload: SalonEventUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_events", "イベントを更新する権限がありません")

    current = _fetch_event(supabase, salon_id, event_id)

    start_at = payload.start_at or current.get("start_at")
    end_at = payload.end_at if payload.end_at is not None else current.get("end_at")
    if isinstance(start_at, str):
        start_at_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    else:
        start_at_dt = start_at
    if isinstance(end_at, str) and end_at is not None:
        end_at_dt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    else:
        end_at_dt = end_at
    _validate_event_dates(start_at_dt, end_at_dt)

    update_data: Dict[str, Any] = {}
    if payload.title is not None:
        update_data["title"] = payload.title
    if payload.description is not None:
        update_data["description"] = payload.description
    if payload.start_at is not None:
        update_data["start_at"] = payload.start_at.isoformat()
    if payload.end_at is not None:
        update_data["end_at"] = payload.end_at.isoformat() if payload.end_at else None
    if payload.location is not None:
        update_data["location"] = payload.location
    if payload.meeting_url is not None:
        update_data["meeting_url"] = payload.meeting_url
    if payload.is_public is not None:
        update_data["is_public"] = payload.is_public
    if payload.capacity is not None:
        update_data["capacity"] = payload.capacity

    if not update_data:
        attendee_counts, attending_map = _get_attendee_stats(supabase, [event_id], user["id"])
        return _map_event_record(
            current,
            attendee_counts.get(event_id, 0),
            attending_map.get(event_id, False),
        )

    response = (
        supabase
        .table("salon_events")
        .update(update_data)
        .eq("id", event_id)
        .eq("salon_id", salon_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="イベントの更新に失敗しました")

    updated = response.data[0]
    attendee_counts, attending_map = _get_attendee_stats(supabase, [event_id], user["id"])
    return _map_event_record(
        updated,
        attendee_counts.get(event_id, 0),
        attending_map.get(event_id, False),
    )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    salon_id: str,
    event_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_events", "イベントを削除する権限がありません")

    _fetch_event(supabase, salon_id, event_id)
    supabase.table("salon_events").delete().eq("id", event_id).eq("salon_id", salon_id).execute()


@router.get("/{event_id}/attendees", response_model=SalonEventAttendeeListResponse)
async def list_attendees(
    salon_id: str,
    event_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_event(supabase, salon_id, event_id)

    count_resp = (
        supabase
        .table("salon_event_attendees")
        .select("id", count="exact")
        .eq("event_id", event_id)
        .execute()
    )
    total = getattr(count_resp, "count", 0) or 0

    range_end = offset + limit - 1
    attendees_resp = (
        supabase
        .table("salon_event_attendees")
        .select("*")
        .eq("event_id", event_id)
        .order("created_at", asc=True)
        .range(offset, range_end)
        .execute()
    )
    records = attendees_resp.data or []
    user_ids = [record.get("user_id") for record in records if record.get("user_id")]

    username_map: Dict[str, str] = {}
    if user_ids:
        users_resp = (
            supabase
            .table("users")
            .select("id, username")
            .in_("id", user_ids)
            .execute()
        )
        for row in users_resp.data or []:
            uid = row.get("id")
            if uid:
                username_map[uid] = row.get("username")

    data = [_map_attendee_record(record, username_map.get(record.get("user_id"))) for record in records]
    return SalonEventAttendeeListResponse(data=data, total=total, limit=limit, offset=offset)


@router.post("/{event_id}/attend", response_model=SalonEventAttendeeResponse, status_code=status.HTTP_201_CREATED)
async def attend_event(
    salon_id: str,
    event_id: str,
    payload: SalonEventAttendRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_event(supabase, salon_id, event_id)

    attendee_resp = (
        supabase
        .table("salon_event_attendees")
        .select("*")
        .eq("event_id", event_id)
        .eq("user_id", user["id"])
        .single()
        .execute()
    )

    status_value = (payload.status or "GOING").upper()
    if status_value not in {"GOING", "INTERESTED", "WAITLIST"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="参加ステータスが不正です")

    if attendee_resp.data:
        response = (
            supabase
            .table("salon_event_attendees")
            .update({
                "status": status_value,
                "note": payload.note,
            })
            .eq("id", attendee_resp.data["id"])
            .execute()
        )
    else:
        count_resp = (
            supabase
            .table("salon_event_attendees")
            .select("id", count="exact")
            .eq("event_id", event_id)
            .execute()
        )
        current_count = getattr(count_resp, "count", 0) or 0
        event_record = _fetch_event(supabase, salon_id, event_id)
        capacity = event_record.get("capacity")
        if capacity and current_count >= capacity:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="イベントの定員に達しています")

        response = supabase.table("salon_event_attendees").insert({
            "event_id": event_id,
            "user_id": user["id"],
            "status": status_value,
            "note": payload.note,
        }).execute()

    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="参加登録に失敗しました")

    record = response.data[0]
    username_map = {user["id"]: user.get("username")}
    return _map_attendee_record(record, username_map.get(record.get("user_id")))


@router.delete("/{event_id}/attend", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_attendance(
    salon_id: str,
    event_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_event(supabase, salon_id, event_id)

    supabase.table("salon_event_attendees").delete().eq("event_id", event_id).eq("user_id", user["id"]).execute()
