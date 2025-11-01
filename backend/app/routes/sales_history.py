"""Seller sales history endpoint."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings
from app.models.sales_history import (
    SalesHistoryResponse,
    SalesNoteRecord,
    SalesProductRecord,
    SalesSalonRecord,
    SalesSummary,
)
from app.utils.auth import decode_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales", tags=["sales"])
security = HTTPBearer()


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        candidate = value
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            logger.debug("Failed to parse datetime", extra={"value": value})
    return datetime.utcnow()


def _get_current_user(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証情報が提供されていません",
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to decode access token", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="トークンの検証に失敗しました")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

    supabase = get_supabase()
    response = (
        supabase
        .table("users")
        .select("id, username, user_type")
        .eq("id", user_id)
        .range(0, 0)
        .execute()
    )
    user = (response.data or [None])[0]
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")
    return user


@router.get("/history", response_model=SalesHistoryResponse)
async def get_sales_history(
    product_limit: int = Query(100, ge=1, le=500, description="取得する商品売上レコードの最大件数"),
    note_limit: int = Query(100, ge=1, le=500, description="取得するNOTE売上レコードの最大件数"),
    salon_limit: int = Query(200, ge=1, le=500, description="取得するサロン会員レコードの最大件数"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SalesHistoryResponse:
    user = _get_current_user(credentials)
    if str(user.get("user_type")) != "seller":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sellerのみアクセス可能です")

    seller_id = user["id"]
    supabase = get_supabase()

    # Load seller-owned entities
    product_map: Dict[str, Dict[str, Any]] = {}
    lp_ids: Set[str] = set()
    product_resp = (
        supabase
        .table("products")
        .select("id, title, lp_id")
        .eq("seller_id", seller_id)
        .execute()
    )
    for record in product_resp.data or []:
        product_id = record.get("id")
        if product_id:
            product_map[product_id] = record
        lp_id = record.get("lp_id")
        if lp_id:
            lp_ids.add(lp_id)

    note_map: Dict[str, Dict[str, Any]] = {}
    note_resp = (
        supabase
        .table("notes")
        .select("id, title, slug")
        .eq("author_id", seller_id)
        .execute()
    )
    for record in note_resp.data or []:
        note_id = record.get("id")
        if note_id:
            note_map[note_id] = record

    salon_map: Dict[str, Dict[str, Any]] = {}
    salon_resp = (
        supabase
        .table("salons")
        .select("id, title")
        .eq("owner_id", seller_id)
        .execute()
    )
    for record in salon_resp.data or []:
        salon_id = record.get("id")
        if salon_id:
            salon_map[salon_id] = record

    lp_slug_map: Dict[str, Optional[str]] = {}
    if lp_ids:
        lp_resp = (
            supabase
            .table("landing_pages")
            .select("id, slug")
            .in_("id", list(lp_ids))
            .execute()
        )
        for record in lp_resp.data or []:
            lp_id = record.get("id")
            if lp_id:
                lp_slug_map[lp_id] = record.get("slug")

    buyer_ids: Set[str] = set()

    # Product point transactions
    product_point_rows: List[Dict[str, Any]] = []
    product_ids = list(product_map.keys())
    if product_ids:
        point_query = (
            supabase
            .table("point_transactions")
            .select("id, user_id, related_product_id, amount, description, created_at")
            .eq("transaction_type", "product_purchase")
            .in_("related_product_id", product_ids)
            .order("created_at", desc=True)
            .range(0, product_limit - 1)
        )
        product_point_rows = point_query.execute().data or []
        for row in product_point_rows:
            buyer_id = row.get("user_id")
            if buyer_id:
                buyer_ids.add(buyer_id)

    # Product yen orders
    product_order_rows: List[Dict[str, Any]] = []
    order_query = (
        supabase
        .table("payment_orders")
        .select("id, user_id, item_id, amount_jpy, metadata, completed_at, updated_at, created_at, payment_method")
        .eq("seller_id", seller_id)
        .eq("item_type", "product")
        .eq("status", "COMPLETED")
        .order("completed_at", desc=True)
        .range(0, product_limit - 1)
    )
    product_order_rows = order_query.execute().data or []
    for row in product_order_rows:
        buyer_id = row.get("user_id")
        if buyer_id:
            buyer_ids.add(buyer_id)

    # Note purchases via points
    note_point_rows: List[Dict[str, Any]] = []
    note_ids = list(note_map.keys())
    if note_ids:
        note_point_query = (
            supabase
            .table("note_purchases")
            .select("id, note_id, buyer_id, points_spent, purchased_at")
            .in_("note_id", note_ids)
            .gt("points_spent", 0)
            .order("purchased_at", desc=True)
            .range(0, note_limit - 1)
        )
        note_point_rows = note_point_query.execute().data or []
        for row in note_point_rows:
            buyer_id = row.get("buyer_id")
            if buyer_id:
                buyer_ids.add(buyer_id)

    # Note yen orders
    note_order_rows: List[Dict[str, Any]] = []
    if note_ids:
        note_order_query = (
            supabase
            .table("payment_orders")
            .select("id, user_id, item_id, amount_jpy, completed_at, updated_at, created_at, payment_method")
            .eq("seller_id", seller_id)
            .eq("item_type", "note")
            .eq("status", "COMPLETED")
            .order("completed_at", desc=True)
            .range(0, note_limit - 1)
        )
        note_order_rows = note_order_query.execute().data or []
        for row in note_order_rows:
            buyer_id = row.get("user_id")
            if buyer_id:
                buyer_ids.add(buyer_id)

    # Salon memberships
    salon_membership_rows: List[Dict[str, Any]] = []
    salon_ids = list(salon_map.keys())
    if salon_ids:
        salon_query = (
            supabase
            .table("salon_memberships")
            .select("id, salon_id, user_id, status, joined_at, last_charged_at, next_charge_at")
            .in_("salon_id", salon_ids)
            .order("joined_at", desc=True)
            .range(0, salon_limit - 1)
        )
        salon_membership_rows = salon_query.execute().data or []
        for row in salon_membership_rows:
            buyer_id = row.get("user_id")
            if buyer_id:
                buyer_ids.add(buyer_id)

    # Load buyer profiles
    buyer_map: Dict[str, Dict[str, Any]] = {}
    if buyer_ids:
        buyers_resp = (
            supabase
            .table("users")
            .select("id, username, profile_image_url")
            .in_("id", list(buyer_ids))
            .execute()
        )
        for record in buyers_resp.data or []:
            buyer_id = record.get("id")
            if buyer_id:
                buyer_map[buyer_id] = record

    # Build product sales records
    product_sales: List[SalesProductRecord] = []
    for row in product_point_rows:
        product_id = row.get("related_product_id")
        product = product_map.get(product_id) if product_id else None
        buyer_id = row.get("user_id")
        buyer_info = buyer_map.get(buyer_id) if buyer_id else None
        amount = row.get("amount")
        amount_points = abs(int(amount)) if amount is not None else 0
        purchased_at = _parse_datetime(row.get("created_at"))
        product_sales.append(
            SalesProductRecord(
                sale_id=row.get("id") or f"tx_{purchased_at.timestamp()}",
                product_id=product_id,
                product_title=product.get("title") if product else None,
                buyer_id=buyer_id,
                buyer_username=buyer_info.get("username") if buyer_info else None,
                buyer_profile_image_url=buyer_info.get("profile_image_url") if buyer_info else None,
                payment_method="points",
                amount_points=amount_points,
                amount_jpy=None,
                purchased_at=purchased_at,
                lp_slug=lp_slug_map.get(product.get("lp_id")) if product else None,
                description=row.get("description"),
            )
        )

    for row in product_order_rows:
        product_id = row.get("item_id")
        product = product_map.get(product_id) if product_id else None
        buyer_id = row.get("user_id")
        buyer_info = buyer_map.get(buyer_id) if buyer_id else None
        purchased_at = _parse_datetime(row.get("completed_at")) if row.get("completed_at") else _parse_datetime(row.get("updated_at") or row.get("created_at"))
        amount_jpy = row.get("amount_jpy")
        lp_slug = None
        if product:
            lp_slug = lp_slug_map.get(product.get("lp_id")) if product.get("lp_id") else None
        product_sales.append(
            SalesProductRecord(
                sale_id=row.get("id"),
                product_id=product_id,
                product_title=product.get("title") if product else None,
                buyer_id=buyer_id,
                buyer_username=buyer_info.get("username") if buyer_info else None,
                buyer_profile_image_url=buyer_info.get("profile_image_url") if buyer_info else None,
                payment_method=str(row.get("payment_method") or "yen"),
                amount_points=0,
                amount_jpy=int(amount_jpy) if amount_jpy is not None else None,
                purchased_at=purchased_at,
                lp_slug=lp_slug,
                description=None,
            )
        )

    product_sales.sort(key=lambda record: record.purchased_at, reverse=True)
    product_sales = product_sales[:product_limit]

    # Build note sales records
    note_sales: List[SalesNoteRecord] = []
    for row in note_point_rows:
        note_id = row.get("note_id")
        note = note_map.get(note_id) if note_id else None
        buyer_id = row.get("buyer_id")
        buyer_info = buyer_map.get(buyer_id) if buyer_id else None
        points_spent = int(row.get("points_spent") or 0)
        purchased_at = _parse_datetime(row.get("purchased_at"))
        note_sales.append(
            SalesNoteRecord(
                sale_id=row.get("id"),
                note_id=note_id or "",
                note_title=note.get("title") if note else None,
                note_slug=note.get("slug") if note else None,
                buyer_id=buyer_id,
                buyer_username=buyer_info.get("username") if buyer_info else None,
                buyer_profile_image_url=buyer_info.get("profile_image_url") if buyer_info else None,
                payment_method="points",
                points_spent=points_spent,
                amount_jpy=None,
                purchased_at=purchased_at,
            )
        )

    for row in note_order_rows:
        note_id = row.get("item_id")
        note = note_map.get(note_id) if note_id else None
        buyer_id = row.get("user_id")
        buyer_info = buyer_map.get(buyer_id) if buyer_id else None
        purchased_at = _parse_datetime(row.get("completed_at")) if row.get("completed_at") else _parse_datetime(row.get("updated_at") or row.get("created_at"))
        amount_jpy = row.get("amount_jpy")
        note_sales.append(
            SalesNoteRecord(
                sale_id=row.get("id"),
                note_id=note_id or "",
                note_title=note.get("title") if note else None,
                note_slug=note.get("slug") if note else None,
                buyer_id=buyer_id,
                buyer_username=buyer_info.get("username") if buyer_info else None,
                buyer_profile_image_url=buyer_info.get("profile_image_url") if buyer_info else None,
                payment_method=str(row.get("payment_method") or "yen"),
                points_spent=0,
                amount_jpy=int(amount_jpy) if amount_jpy is not None else None,
                purchased_at=purchased_at,
            )
        )

    note_sales.sort(key=lambda record: record.purchased_at, reverse=True)
    note_sales = note_sales[:note_limit]

    # Build salon membership records
    salon_sales: List[SalesSalonRecord] = []
    for row in salon_membership_rows:
        salon_id = row.get("salon_id")
        salon = salon_map.get(salon_id) if salon_id else None
        buyer_id = row.get("user_id")
        buyer_info = buyer_map.get(buyer_id) if buyer_id else None
        salon_sales.append(
            SalesSalonRecord(
                membership_id=row.get("id"),
                salon_id=salon_id or "",
                salon_title=salon.get("title") if salon else None,
                buyer_id=buyer_id,
                buyer_username=buyer_info.get("username") if buyer_info else None,
                buyer_profile_image_url=buyer_info.get("profile_image_url") if buyer_info else None,
                status=str(row.get("status") or "").upper(),
                joined_at=_parse_datetime(row.get("joined_at")),
                next_charge_at=_parse_datetime(row.get("next_charge_at")) if row.get("next_charge_at") else None,
                last_charged_at=_parse_datetime(row.get("last_charged_at")) if row.get("last_charged_at") else None,
            )
        )

    salon_sales.sort(key=lambda record: record.joined_at, reverse=True)
    salon_sales = salon_sales[:salon_limit]

    total_points_revenue = sum(record.amount_points for record in product_sales) + sum(record.points_spent for record in note_sales)
    total_yen_revenue = sum(record.amount_jpy or 0 for record in product_sales) + sum(record.amount_jpy or 0 for record in note_sales)

    summary = SalesSummary(
        product_orders=len(product_sales),
        note_orders=len(note_sales),
        salon_memberships=len(salon_sales),
        total_points_revenue=total_points_revenue,
        total_yen_revenue=total_yen_revenue,
    )

    return SalesHistoryResponse(
        summary=summary,
        products=product_sales,
        notes=note_sales,
        salons=salon_sales,
    )
