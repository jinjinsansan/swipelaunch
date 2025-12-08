"""Salon management endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salons import (
    ManualSalonMemberRequest,
    NoteSalonAccessRequest,
    NoteSalonAccessResponse,
    SalonCreateRequest,
    SalonListResponse,
    SalonMemberListResponse,
    SalonMemberResponse,
    SalonMemberUpdateRequest,
    SalonResponse,
    SalonUpdateRequest,
)
from app.utils.auth import decode_access_token
from app.services import note_notifications


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/salons", tags=["salons"])
security = HTTPBearer()

MANUAL_INVITE_SOURCE = "manual_invite"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_username(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    return normalized or None


def _to_iso_string(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _build_manual_metadata(
    existing_metadata: Optional[Dict[str, Any]],
    memo: Optional[str],
    actor_id: str,
    timestamp: str,
    *,
    expires_at: Optional[str] = None,
    clear_expires: bool = False,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = existing_metadata.copy() if isinstance(existing_metadata, dict) else {}
    manual_block = metadata.get("manual_invite") if isinstance(metadata.get("manual_invite"), dict) else {}
    manual_block = manual_block.copy()
    manual_block["updated_by"] = actor_id
    manual_block["updated_at"] = timestamp
    if memo is not None:
        manual_block["memo"] = memo
    elif "memo" not in manual_block:
        manual_block["memo"] = None

    if expires_at is not None:
        manual_block["expires_at"] = expires_at
    elif clear_expires:
        manual_block.pop("expires_at", None)

    metadata["source"] = MANUAL_INVITE_SOURCE
    metadata["manual_invite"] = manual_block
    return metadata


def _upsert_manual_subscription(
    supabase,
    salon: Dict[str, Any],
    user_id: str,
    status: str,
    memo: Optional[str],
    actor_id: str,
    timestamp: str,
    *,
    expires_at: Optional[str] = None,
    clear_expires: bool = False,
) -> None:
    response = (
        supabase
        .table("user_subscriptions")
        .select("id,metadata")
        .eq("user_id", user_id)
        .eq("salon_id", salon.get("id"))
        .eq("plan_key", MANUAL_INVITE_SOURCE)
        .limit(1)
        .execute()
    )
    existing = response.data[0] if response.data else None
    metadata = _build_manual_metadata(
        existing.get("metadata") if existing else None,
        memo,
        actor_id,
        timestamp,
        expires_at=expires_at,
        clear_expires=clear_expires,
    )

    if existing and existing.get("id"):
        supabase.table("user_subscriptions").update({
            "status": status,
            "metadata": metadata,
            "updated_at": timestamp,
        }).eq("id", existing["id"]).execute()
        return

    supabase.table("user_subscriptions").insert({
        "user_id": user_id,
        "plan_key": MANUAL_INVITE_SOURCE,
        "subscription_plan_id": salon.get("subscription_plan_id") or "manual_invite",
        "points_per_cycle": 0,
        "usd_amount": 0,
        "status": status,
        "metadata": metadata,
        "seller_id": salon.get("owner_id"),
        "seller_username": salon.get("owner_username"),
        "salon_id": salon.get("id"),
    }).execute()


def _extract_user_payload(user_value: Any) -> Dict[str, Any]:
    if isinstance(user_value, dict):
        return user_value
    if isinstance(user_value, list) and user_value:
        first = user_value[0]
        if isinstance(first, dict):
            return first
    return {}


def _serialize_member(row: Dict[str, Any], user_override: Optional[Dict[str, Any]] = None) -> SalonMemberResponse:
    raw_metadata = row.get("metadata")
    metadata = raw_metadata.copy() if isinstance(raw_metadata, dict) else None
    manual_block = metadata.get("manual_invite") if isinstance(metadata, dict) and isinstance(metadata.get("manual_invite"), dict) else None
    manual_expires_at = _parse_iso_datetime(manual_block.get("expires_at")) if manual_block else None

    user_payload = user_override or _extract_user_payload(row.get("user"))

    return SalonMemberResponse(
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
        metadata=metadata,
        user_email=user_payload.get("email"),
        user_username=user_payload.get("username"),
        user_display_name=user_payload.get("display_name"),
        manual_expires_at=manual_expires_at,
    )


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
        subscription_plan_id=record.get("subscription_plan_id", ""),
        subscription_external_id=record.get("subscription_external_id"),
        monthly_price_jpy=record.get("monthly_price_jpy"),
        allow_point_subscription=bool(record.get("allow_point_subscription", True)),
        allow_jpy_subscription=bool(record.get("allow_jpy_subscription", False)),
        tax_rate=record.get("tax_rate"),
        tax_inclusive=bool(record.get("tax_inclusive", True)),
        is_active=bool(record.get("is_active", True)),
        status=record.get("status", "approved"),
        moderation_notes=record.get("moderation_notes"),
        member_count=member_count,
        is_featured=bool(record.get("is_featured", False)),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        introductory_offer_enabled=bool(record.get("introductory_offer_enabled", False)),
        introductory_offer_type=record.get("introductory_offer_type"),
        show_member_count_public=bool(record.get("show_member_count_public", True)),
    )


@router.post("", response_model=SalonResponse, status_code=status.HTTP_201_CREATED)
async def create_salon(
    payload: SalonCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    _ensure_seller(user)

    supabase = get_supabase_client()

    allow_point_subscription = payload.allow_point_subscription
    allow_jpy_subscription = payload.allow_jpy_subscription
    introductory_offer_enabled = bool(payload.introductory_offer_enabled)
    introductory_offer_type = payload.introductory_offer_type

    if introductory_offer_enabled:
        resolved_offer_type = introductory_offer_type or "first_month_free_direct"
        if resolved_offer_type != "first_month_free_direct":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="サポートされていないイントロオファーの種類です",
            )
        allow_point_subscription = False
        allow_jpy_subscription = True
        introductory_offer_type = resolved_offer_type
    else:
        introductory_offer_type = None

    salon_data = {
        "owner_id": user["id"],
        "title": payload.title,
        "description": payload.description,
        "thumbnail_url": payload.thumbnail_url,
        "subscription_plan_id": payload.subscription_plan_id,
        "subscription_external_id": payload.subscription_external_id,
        "monthly_price_jpy": payload.monthly_price_jpy,
        "allow_point_subscription": allow_point_subscription,
        "allow_jpy_subscription": allow_jpy_subscription,
        "tax_rate": payload.tax_rate,
        "tax_inclusive": payload.tax_inclusive,
        "is_active": True,
        "introductory_offer_enabled": introductory_offer_enabled,
        "introductory_offer_type": introductory_offer_type,
        "show_member_count_public": payload.show_member_count_public,
    }

    response = supabase.table("salons").insert(salon_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="サロンの作成に失敗しました")
    created_row = response.data[0]

    note_notifications.handle_salon_published(supabase, created_row)

    return _map_salon(created_row, member_count=0)


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

    # Find linked LP (reverse lookup from landing_pages.salon_id)
    try:
        lp_response = (
            supabase.table("landing_pages")
            .select("id")
            .eq("salon_id", salon_id)
            .eq("seller_id", user["id"])
            .execute()
        )
        linked_lp_id = lp_response.data[0]["id"] if lp_response.data and len(lp_response.data) > 0 else None
    except Exception:
        linked_lp_id = None

    salon_data = _map_salon(record, member_count=member_count)
    salon_dict = salon_data.model_dump()
    salon_dict["lp_id"] = linked_lp_id
    
    return SalonResponse(**salon_dict)


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
    if payload.is_active is not None:
        update_data["is_active"] = payload.is_active
    if payload.monthly_price_jpy is not None:
        update_data["monthly_price_jpy"] = payload.monthly_price_jpy

    if payload.introductory_offer_enabled is not None or payload.introductory_offer_type is not None:
        new_enabled = (
            payload.introductory_offer_enabled
            if payload.introductory_offer_enabled is not None
            else bool(current.get("introductory_offer_enabled", False))
        )
        new_type = (
            payload.introductory_offer_type
            if payload.introductory_offer_type is not None
            else current.get("introductory_offer_type")
        )

        if new_enabled:
            resolved_type = new_type or "first_month_free_direct"
            if resolved_type != "first_month_free_direct":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="サポートされていないイントロオファーの種類です",
                )
            update_data["introductory_offer_enabled"] = True
            update_data["introductory_offer_type"] = resolved_type
            update_data["allow_point_subscription"] = False
            update_data["allow_jpy_subscription"] = True
        else:
            update_data["introductory_offer_enabled"] = False
            update_data["introductory_offer_type"] = None
            if payload.allow_point_subscription is not None:
                update_data["allow_point_subscription"] = payload.allow_point_subscription
            if payload.allow_jpy_subscription is not None:
                update_data["allow_jpy_subscription"] = payload.allow_jpy_subscription
    else:
        if payload.allow_point_subscription is not None:
            update_data["allow_point_subscription"] = payload.allow_point_subscription
        if payload.allow_jpy_subscription is not None:
            update_data["allow_jpy_subscription"] = payload.allow_jpy_subscription
    if payload.tax_rate is not None:
        update_data["tax_rate"] = payload.tax_rate
    if payload.tax_inclusive is not None:
        update_data["tax_inclusive"] = payload.tax_inclusive
    if payload.show_member_count_public is not None:
        update_data["show_member_count_public"] = payload.show_member_count_public

    supabase = get_supabase_client()

    # Handle LP linking
    if payload.lp_id is not None:
        try:
            if payload.lp_id:
                # Verify LP belongs to user
                lp_response = (
                    supabase.table("landing_pages")
                    .select("id, salon_id")
                    .eq("id", payload.lp_id)
                    .eq("seller_id", user["id"])
                    .execute()
                )
                
                if not lp_response.data or len(lp_response.data) == 0:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたLPが見つかりません。自分が作成したLPを選択してください")

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
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to handle LP linking: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"LP紐づけ処理に失敗しました: {str(e)}")

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

    if updated:
        note_notifications.handle_salon_published(supabase, updated, previous_row=current)

    return _map_salon(updated, member_count=member_count)



@router.delete("/{salon_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_salon(
    salon_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Response:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    # Ensure salon belongs to user
    _ = _get_salon_owned_by_user(salon_id, user["id"])

    supabase = get_supabase_client()
    member_count_resp = (
        supabase.table("salon_memberships")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
        .execute()
    )
    member_count = getattr(member_count_resp, "count", 0) or 0
    if member_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="会員が存在するためサロンを削除できません",
        )

    delete_response = (
        supabase.table("salons")
        .delete()
        .eq("id", salon_id)
        .eq("owner_id", user["id"])
        .execute()
    )
    if delete_response.data is None:
        logger.warning("Supabase deletion returned no payload", extra={"salon_id": salon_id})

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        .select(
            "*, user:users!salon_memberships_user_id_fkey(id,username,display_name,email)",
            count="exact",
        )
        .eq("salon_id", salon_id)
        .order("joined_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status_filter:
        query = query.eq("status", status_filter)

    response = query.execute()
    rows = response.data or []
    members = [_serialize_member(row) for row in rows]
    total = getattr(response, "count", len(rows)) or 0

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


@router.post("/{salon_id}/members/manual", response_model=SalonMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_manual_salon_member(
    salon_id: str,
    payload: ManualSalonMemberRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SalonMemberResponse:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    salon = _get_salon_owned_by_user(salon_id, user["id"])

    supabase = get_supabase_client()

    email = _normalize_email(payload.email)
    username = _normalize_username(payload.username)

    user_query = supabase.table("users").select("id,username,email").limit(1)
    if email and username:
        user_query = user_query.or_(f"email.ilike.{email},username.eq.{username}")
    elif email:
        user_query = user_query.ilike("email", email)
    else:
        user_query = user_query.eq("username", username)

    user_response = user_query.execute()
    target_user = user_response.data[0] if user_response.data else None
    target_user_id = target_user.get("id") if target_user else None
    if not target_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="対象ユーザーが見つかりません")

    membership_response = (
        supabase
        .table("salon_memberships")
        .select("*")
        .eq("salon_id", salon_id)
        .eq("user_id", target_user_id)
        .limit(1)
        .execute()
    )
    existing_membership = membership_response.data[0] if membership_response.data else None

    now_iso = _now_utc_iso()
    normalized_status = payload.status.upper()
    expires_iso = _to_iso_string(payload.expires_at)
    manual_metadata = _build_manual_metadata(
        existing_membership.get("metadata") if existing_membership else None,
        payload.memo,
        user["id"],
        now_iso,
        expires_at=expires_iso,
    )

    membership_row: Dict[str, Any]
    if existing_membership and existing_membership.get("id"):
        existing_status = (existing_membership.get("status") or "").upper()
        if existing_status not in {"CANCELED", "CANCELLED"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="このユーザーは既に会員です")

        update_payload: Dict[str, Any] = {
            "status": normalized_status,
            "metadata": manual_metadata,
            "updated_at": now_iso,
        }
        if normalized_status == "ACTIVE" and not existing_membership.get("joined_at"):
            update_payload["joined_at"] = now_iso
        if normalized_status == "CANCELED":
            update_payload["canceled_at"] = now_iso
        else:
            update_payload["canceled_at"] = None

        update_response = (
            supabase
            .table("salon_memberships")
            .update(update_payload)
            .eq("id", existing_membership["id"])
            .execute()
        )
        membership_row = update_response.data[0] if update_response.data else {**existing_membership, **update_payload}
    else:
        insert_payload: Dict[str, Any] = {
            "salon_id": salon_id,
            "user_id": target_user_id,
            "status": normalized_status,
            "metadata": manual_metadata,
            "joined_at": now_iso,
        }
        if normalized_status == "CANCELED":
            insert_payload["canceled_at"] = now_iso

        insert_response = supabase.table("salon_memberships").insert(insert_payload).execute()
        membership_row = insert_response.data[0] if insert_response.data else insert_payload

    _upsert_manual_subscription(
        supabase,
        salon,
        target_user_id,
        normalized_status,
        payload.memo,
        user["id"],
        now_iso,
        expires_at=expires_iso,
    )

    return _serialize_member(membership_row, user_override=target_user)


@router.patch("/{salon_id}/members/{member_id}", response_model=SalonMemberResponse)
async def update_manual_salon_member(
    salon_id: str,
    member_id: str,
    payload: SalonMemberUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SalonMemberResponse:
    user = _get_current_user(credentials)
    _ensure_seller(user)

    salon = _get_salon_owned_by_user(salon_id, user["id"])
    supabase = get_supabase_client()

    membership_response = (
        supabase
        .table("salon_memberships")
        .select("*, user:users!salon_memberships_user_id_fkey(id,username,display_name,email)")
        .eq("id", member_id)
        .eq("salon_id", salon_id)
        .limit(1)
        .execute()
    )
    membership_row = membership_response.data[0] if membership_response.data else None
    if not membership_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員が見つかりません")

    metadata = membership_row.get("metadata") if isinstance(membership_row.get("metadata"), dict) else {}
    if metadata.get("source") != MANUAL_INVITE_SOURCE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手動で追加した会員のみ編集できます")

    status_requested = payload.status.upper() if payload.status else None
    expires_iso = _to_iso_string(payload.expires_at)
    has_metadata_update = (
        payload.memo is not None
        or payload.expires_at is not None
        or payload.clear_expires_at
    )

    if not status_requested and not has_metadata_update:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新する項目を指定してください")

    now_iso = _now_utc_iso()
    update_payload: Dict[str, Any] = {"updated_at": now_iso}
    current_status = (membership_row.get("status") or "").upper()
    status_changed = False

    if status_requested:
        update_payload["status"] = status_requested
        status_changed = status_requested != current_status
        if status_requested == "CANCELED":
            update_payload["canceled_at"] = now_iso
        else:
            update_payload["canceled_at"] = None
            if status_requested == "ACTIVE" and not membership_row.get("joined_at"):
                update_payload["joined_at"] = now_iso

    if has_metadata_update:
        update_payload["metadata"] = _build_manual_metadata(
            membership_row.get("metadata"),
            payload.memo,
            user["id"],
            now_iso,
            expires_at=expires_iso,
            clear_expires=payload.clear_expires_at,
        )

    update_response = (
        supabase
        .table("salon_memberships")
        .update(update_payload)
        .eq("id", member_id)
        .execute()
    )
    updated_row = update_response.data[0] if update_response.data else {**membership_row, **update_payload}
    updated_row["user"] = membership_row.get("user")

    if status_changed or has_metadata_update:
        _upsert_manual_subscription(
            supabase,
            salon,
            membership_row.get("user_id"),
            update_payload.get("status", current_status),
            payload.memo,
            user["id"],
            now_iso,
            expires_at=expires_iso,
            clear_expires=payload.clear_expires_at,
        )

    user_payload = _extract_user_payload(membership_row.get("user"))
    return _serialize_member(updated_row, user_override=user_payload)
