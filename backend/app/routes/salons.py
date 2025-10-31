"""Salon management endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salons import (
    NoteSalonAccessRequest,
    NoteSalonAccessResponse,
    SalonCreateRequest,
    SalonListResponse,
    SalonMemberListResponse,
    SalonMemberResponse,
    SalonResponse,
    SalonUpdateRequest,
)
from app.utils.auth import decode_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/salons", tags=["salons"])
security = HTTPBearer()


def _get_current_user(credentials: HTTPAuthorizationCredentials) -> Dict[str, str]:
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

    supabase = get_supabase_client()
    user_response = supabase.table("users").select("id,user_type").eq("id", user_id).single().execute()
    if not user_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")
    return user_response.data


def _ensure_seller(user: Dict[str, str]) -> None:
    if user.get("user_type") != "seller":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="この操作はSellerのみが利用できます")


def _map_salon(record: Dict[str, Any], member_count: int = 0) -> SalonResponse:
    return SalonResponse(
        id=record.get("id"),
        owner_id=record.get("owner_id"),
        title=record.get("title", ""),
        description=record.get("description"),
        thumbnail_url=record.get("thumbnail_url"),
        category=record.get("category"),
        subscription_plan_id=record.get("subscription_plan_id", ""),
        subscription_external_id=record.get("subscription_external_id"),
        is_active=bool(record.get("is_active", True)),
        member_count=member_count,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


@router.post("", response_model=SalonResponse, status_code=status.HTTP_201_CREATED)
async def create_salon(
    payload: SalonCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    _ensure_seller(user)

    supabase = get_supabase_client()

    salon_data = {
        "owner_id": user["id"],
        "title": payload.title,
        "description": payload.description,
        "thumbnail_url": payload.thumbnail_url,
        "category": payload.category,
        "subscription_plan_id": payload.subscription_plan_id,
        "subscription_external_id": payload.subscription_external_id,
        "is_active": True,
    }

    response = supabase.table("salons").insert(salon_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="サロンの作成に失敗しました")

    return _map_salon(response.data[0], member_count=0)


@router.get("", response_model=SalonListResponse)
async def list_salons(credentials: HTTPAuthorizationCredentials = Depends(security)) -> SalonListResponse:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    supabase = get_supabase_client()
    response = (
        supabase.table("salons")
        .select("*")
        .eq("owner_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )

    records: List[Dict[str, Any]] = response.data or []
    salon_ids = [record.get("id") for record in records if record.get("id")]

    member_counts: Dict[str, int] = {}
    if salon_ids:
        membership_response = (
            supabase.table("salon_memberships")
            .select("salon_id")
            .in_("salon_id", salon_ids)
            .execute()
        )
        for membership in membership_response.data or []:
            salon_id = membership.get("salon_id")
            if salon_id:
                member_counts[salon_id] = member_counts.get(salon_id, 0) + 1

    salons = [_map_salon(record, member_count=member_counts.get(record.get("id"), 0)) for record in records]
    return SalonListResponse(data=salons)


def _get_salon_owned_by_user(salon_id: str, owner_id: str) -> Dict[str, Any]:
    supabase = get_supabase_client()
    response = (
        supabase.table("salons")
        .select("*")
        .eq("id", salon_id)
        .eq("owner_id", owner_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")
    return response.data


@router.get("/{salon_id}", response_model=SalonResponse)
async def get_salon(
    salon_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SalonResponse:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    record = _get_salon_owned_by_user(salon_id, user["id"])

    supabase = get_supabase_client()
    member_count_resp = (
        supabase.table("salon_memberships")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
        .execute()
    )
    member_count = getattr(member_count_resp, "count", 0) or 0

    return _map_salon(record, member_count=member_count)


@router.patch("/{salon_id}", response_model=SalonResponse)
async def update_salon(
    salon_id: str,
    payload: SalonUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SalonResponse:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    current = _get_salon_owned_by_user(salon_id, user["id"])

    update_data: Dict[str, any] = {}
    if payload.title is not None:
        update_data["title"] = payload.title
    if payload.description is not None:
        update_data["description"] = payload.description
    if payload.thumbnail_url is not None:
        update_data["thumbnail_url"] = payload.thumbnail_url
    if payload.category is not None:
        update_data["category"] = payload.category
    if payload.is_active is not None:
        update_data["is_active"] = payload.is_active

    supabase = get_supabase_client()

    # Handle LP linking
    if payload.lp_id is not None:
        if payload.lp_id:
            # Verify LP belongs to user
            lp_response = (
                supabase.table("landing_pages")
                .select("id, salon_id")
                .eq("id", payload.lp_id)
                .eq("seller_id", user["id"])
                .single()
                .execute()
            )
            if not lp_response.data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたLPが見つかりません")

            # Update LP to link to this salon
            supabase.table("landing_pages").update({"salon_id": salon_id}).eq("id", payload.lp_id).execute()

            # If there was an old LP linked to this salon, unlink it
            old_lp_response = (
                supabase.table("landing_pages")
                .select("id")
                .eq("salon_id", salon_id)
                .neq("id", payload.lp_id)
                .execute()
            )
            if old_lp_response.data:
                for old_lp in old_lp_response.data:
                    supabase.table("landing_pages").update({"salon_id": None}).eq("id", old_lp["id"]).execute()
        else:
            # Unlink any LP currently linked to this salon
            supabase.table("landing_pages").update({"salon_id": None}).eq("salon_id", salon_id).execute()

    if not update_data:
        # Even if no salon fields changed, LP linking may have happened
        updated = current
    else:
        response = (
            supabase.table("salons")
            .update(update_data)
            .eq("id", salon_id)
            .eq("owner_id", user["id"])
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="サロンの更新に失敗しました")
        updated = response.data[0]

    member_count_resp = (
        supabase.table("salon_memberships")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
        .execute()
    )
    member_count = getattr(member_count_resp, "count", 0) or 0

    return _map_salon(updated, member_count=member_count)


@router.get("/{salon_id}/members", response_model=SalonMemberListResponse)
async def list_salon_members(
    salon_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    status_filter: Optional[str] = Query(None, description="状態でフィルタ (ACTIVE/PENDING/UNPAIDなど)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SalonMemberListResponse:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    _ = _get_salon_owned_by_user(salon_id, user["id"])

    supabase = get_supabase_client()
    query = (
        supabase.table("salon_memberships")
        .select("*", count="exact")
        .eq("salon_id", salon_id)
        .order("joined_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status_filter:
        query = query.eq("status", status_filter)

    response = query.execute()

    members = [
        SalonMemberResponse(
            id=row.get("id"),
            salon_id=row.get("salon_id"),
            user_id=row.get("user_id"),
            status=row.get("status", ""),
            recurrent_payment_id=row.get("recurrent_payment_id"),
            subscription_session_external_id=row.get("subscription_session_external_id"),
            last_event_type=row.get("last_event_type"),
            joined_at=row.get("joined_at"),
            last_charged_at=row.get("last_charged_at"),
            next_charge_at=row.get("next_charge_at"),
            canceled_at=row.get("canceled_at"),
        )
        for row in response.data or []
    ]

    total = getattr(response, "count", None) or len(members)
    return SalonMemberListResponse(data=members, total=total, limit=limit, offset=offset)


@router.post("/{salon_id}/notes/{note_id}/access", response_model=NoteSalonAccessResponse)
async def set_note_salon_access(
    salon_id: str,
    note_id: str,
    payload: NoteSalonAccessRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> NoteSalonAccessResponse:
    """Update list of salons that grant free access for a note. For now enforce ownership."""

    user = _get_current_user(credentials)
    _ensure_seller(user)

    supabase = get_supabase_client()

    # Ensure salon belongs to user (note access API is per note but we keep validation simple)
    _get_salon_owned_by_user(salon_id, user["id"])

    # Ensure note belongs to user
    note_response = (
        supabase.table("notes")
        .select("id, author_id")
        .eq("id", note_id)
        .eq("author_id", user["id"])
        .single()
        .execute()
    )
    if not note_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    # Sanitize salon IDs (must belong to user)
    salon_ids = list({sid for sid in payload.salon_ids if isinstance(sid, str) and sid})
    if salon_ids:
        owned_salons = (
            supabase.table("salons")
            .select("id")
            .eq("owner_id", user["id"])
            .in_("id", salon_ids)
            .execute()
        )
        owned_ids = {row.get("id") for row in owned_salons.data or []}
        salon_ids = [sid for sid in salon_ids if sid in owned_ids]

    # Remove existing access entries for this note owned by user
    supabase.table("note_salon_access").delete().eq("note_id", note_id).execute()

    if salon_ids:
        records = [
            {"note_id": note_id, "salon_id": sid, "allow_free_access": True}
            for sid in salon_ids
        ]
        supabase.table("note_salon_access").insert(records).execute()

    return NoteSalonAccessResponse(salon_ids=salon_ids)
