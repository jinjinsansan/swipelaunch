"""Salon role and permission management endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salon_roles import (
    SalonRoleAssignRequest,
    SalonRoleListResponse,
    SalonRoleResponse,
    SalonRoleCreateRequest,
    SalonRoleUpdateRequest,
)
from app.routes.salon_events import _get_salon_and_access  # reuse membership helper
from app.utils.auth import decode_access_token
from app.utils.salon_permissions import ensure_permission, get_user_permissions


router = APIRouter(prefix="/salons/{salon_id}/roles", tags=["salon-roles"])
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


def _get_role_or_404(supabase, salon_id: str, role_id: str) -> Dict[str, Any]:
    response = (
        supabase
        .table("salon_roles")
        .select("*")
        .eq("id", role_id)
        .eq("salon_id", salon_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ロールが見つかりません")
    return response.data


def _build_role_response(role: Dict[str, Any], member_counts: Dict[str, int]) -> SalonRoleResponse:
    role_id = role.get("id")
    return SalonRoleResponse(
        id=role_id,
        salon_id=role.get("salon_id"),
        name=role.get("name", ""),
        description=role.get("description"),
        is_default=bool(role.get("is_default", False)),
        manage_feed=bool(role.get("manage_feed", False)),
        manage_events=bool(role.get("manage_events", False)),
        manage_assets=bool(role.get("manage_assets", False)),
        manage_announcements=bool(role.get("manage_announcements", False)),
        manage_members=bool(role.get("manage_members", False)),
        manage_roles=bool(role.get("manage_roles", False)),
        created_at=role.get("created_at"),
        updated_at=role.get("updated_at"),
        assigned_member_count=member_counts.get(role_id, 0),
    )


def _fetch_member_counts(supabase, salon_id: str) -> Dict[str, int]:
    response = (
        supabase
        .table("salon_member_roles")
        .select("role_id")
        .eq("salon_id", salon_id)
        .execute()
    )
    counts: Dict[str, int] = {}
    for row in response.data or []:
        role_id = row.get("role_id")
        if role_id:
            counts[role_id] = counts.get(role_id, 0) + 1
    return counts


@router.get("", response_model=SalonRoleListResponse)
async def list_roles(
    salon_id: str,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    ensure_permission(permissions, "manage_roles", "ロールを閲覧する権限がありません")

    range_end = offset + limit - 1
    roles_resp = (
        supabase
        .table("salon_roles")
        .select("*")
        .eq("salon_id", salon_id)
        .order("created_at", desc=False)
        .range(offset, range_end)
        .execute()
    )
    roles = roles_resp.data or []

    count_resp = (
        supabase
        .table("salon_roles")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
        .execute()
    )
    total = getattr(count_resp, "count", 0) or 0

    member_counts = _fetch_member_counts(supabase, salon_id)
    data = [_build_role_response(role, member_counts) for role in roles]

    return SalonRoleListResponse(data=data, total=total)


@router.post("", response_model=SalonRoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    salon_id: str,
    payload: SalonRoleCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    ensure_permission(permissions, "manage_roles", "ロールを作成する権限がありません")

    role_data = {
        "salon_id": salon_id,
        "name": payload.name.strip(),
        "description": payload.description,
        "is_default": payload.is_default,
        "manage_feed": payload.manage_feed,
        "manage_events": payload.manage_events,
        "manage_assets": payload.manage_assets,
        "manage_announcements": payload.manage_announcements,
        "manage_members": payload.manage_members,
        "manage_roles": payload.manage_roles,
    }

    response = supabase.table("salon_roles").insert(role_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ロールの作成に失敗しました")

    role = response.data[0]
    return _build_role_response(role, member_counts={})


@router.patch("/{role_id}", response_model=SalonRoleResponse)
async def update_role(
    salon_id: str,
    role_id: str,
    payload: SalonRoleUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    ensure_permission(permissions, "manage_roles", "ロールを更新する権限がありません")

    current = _get_role_or_404(supabase, salon_id, role_id)

    update_data: Dict[str, Any] = {}
    for field in (
        "name",
        "description",
        "is_default",
        "manage_feed",
        "manage_events",
        "manage_assets",
        "manage_announcements",
        "manage_members",
        "manage_roles",
    ):
        value = getattr(payload, field)
        if value is not None:
            if field == "name" and isinstance(value, str):
                update_data[field] = value.strip()
            else:
                update_data[field] = value

    if not update_data:
        return _build_role_response(current, _fetch_member_counts(supabase, salon_id))

    response = (
        supabase
        .table("salon_roles")
        .update(update_data)
        .eq("id", role_id)
        .eq("salon_id", salon_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ロールの更新に失敗しました")

    updated = response.data[0]
    member_counts = _fetch_member_counts(supabase, salon_id)
    return _build_role_response(updated, member_counts)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    salon_id: str,
    role_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    ensure_permission(permissions, "manage_roles", "ロールを削除する権限がありません")

    role = _get_role_or_404(supabase, salon_id, role_id)
    if role.get("is_default"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="デフォルトロールは削除できません")

    supabase.table("salon_roles").delete().eq("id", role_id).eq("salon_id", salon_id).execute()


@router.post("/{role_id}/assign", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
async def assign_role(
    salon_id: str,
    role_id: str,
    payload: SalonRoleAssignRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    ensure_permission(permissions, "manage_members", "メンバーのロールを変更する権限がありません")

    _get_role_or_404(supabase, salon_id, role_id)

    membership_resp = (
        supabase
        .table("salon_memberships")
        .select("status")
        .eq("salon_id", salon_id)
        .eq("user_id", payload.user_id)
        .maybe_single()
        .execute()
    )
    membership = membership_resp.data
    if not membership or str(membership.get("status", "")).upper() != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="対象ユーザーは有効なサロンメンバーではありません")

    existing = (
        supabase
        .table("salon_member_roles")
        .select("id")
        .eq("salon_id", salon_id)
        .eq("role_id", role_id)
        .eq("user_id", payload.user_id)
        .maybe_single()
        .execute()
    )

    if existing.data:
        assignment_id = existing.data.get("id")
    else:
        insert_resp = (
            supabase
            .table("salon_member_roles")
            .insert(
                {
                    "salon_id": salon_id,
                    "role_id": role_id,
                    "user_id": payload.user_id,
                    "assigned_by": user["id"],
                }
            )
            .execute()
        )
        if not insert_resp.data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ロールの付与に失敗しました")
        assignment_id = insert_resp.data[0].get("id")

    return {
        "assignment_id": assignment_id,
        "role_id": role_id,
        "user_id": payload.user_id,
    }


@router.delete("/{role_id}/assign/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_role(
    salon_id: str,
    role_id: str,
    user_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    ensure_permission(permissions, "manage_members", "メンバーのロールを変更する権限がありません")

    _get_role_or_404(supabase, salon_id, role_id)

    supabase.table("salon_member_roles").delete().eq("salon_id", salon_id).eq("role_id", role_id).eq("user_id", user_id).execute()
