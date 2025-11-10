from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from supabase import Client


def load_payment_method_or_404(
    supabase: Client,
    *,
    user_id: str,
    record_id: str,
    include_revoked: bool = False,
) -> Dict[str, Any]:
    try:
        response = (
            supabase
            .table("one_lat_payment_methods")
            .select("*")
            .eq("id", record_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="支払い方法の取得に失敗しました"
        ) from exc

    row = response.data if response else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定した支払い方法が見つかりません"
        )

    if not include_revoked and row.get("revoked_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定した支払い方法は無効化されています"
        )

    return row


def map_payment_method_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "brand": row.get("brand"),
        "brand_label": (row.get("metadata") or {}).get("brand_label"),
        "last4": row.get("last4"),
        "exp_month": row.get("exp_month"),
        "exp_year": row.get("exp_year"),
        "is_default": bool(row.get("is_default")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "revoked_at": row.get("revoked_at"),
    }
