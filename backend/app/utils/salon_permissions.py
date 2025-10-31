"""Utility helpers for salon role-based permissions."""

from __future__ import annotations

from typing import Dict, Iterable

from fastapi import HTTPException, status

from app.models.salon_roles import PERMISSION_FIELDS, SalonRolePermissions


def _empty_permissions() -> SalonRolePermissions:
    return SalonRolePermissions()


def _permissions_from_records(records: Iterable[dict]) -> SalonRolePermissions:
    merged = {field: False for field in PERMISSION_FIELDS}
    for record in records:
        for field in PERMISSION_FIELDS:
            if record.get(field):
                merged[field] = True
    return SalonRolePermissions(**merged)


def build_owner_permissions() -> SalonRolePermissions:
    return SalonRolePermissions(**{field: True for field in PERMISSION_FIELDS})


def get_user_permissions(supabase, salon_id: str, user_id: str, *, is_owner: bool) -> SalonRolePermissions:
    if is_owner:
        return build_owner_permissions()

    default_roles_resp = (
        supabase
        .table("salon_roles")
        .select("*")
        .eq("salon_id", salon_id)
        .eq("is_default", True)
        .execute()
    )
    default_roles = default_roles_resp.data or []

    assignments_resp = (
        supabase
        .table("salon_member_roles")
        .select("role_id")
        .eq("salon_id", salon_id)
        .eq("user_id", user_id)
        .execute()
    )
    role_ids = [row.get("role_id") for row in assignments_resp.data or [] if row.get("role_id")]

    role_records = []
    if role_ids:
        roles_resp = (
            supabase
            .table("salon_roles")
            .select("*")
            .in_("id", role_ids)
            .execute()
        )
        role_records = roles_resp.data or []

    if not role_records and not default_roles:
        return _empty_permissions()

    return _permissions_from_records([*default_roles, *role_records])


def ensure_permission(permissions: SalonRolePermissions, field: str, message: str) -> None:
    if not getattr(permissions, field, False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def permissions_to_dict(permissions: SalonRolePermissions) -> Dict[str, bool]:
    return {field: getattr(permissions, field, False) for field in PERMISSION_FIELDS}
