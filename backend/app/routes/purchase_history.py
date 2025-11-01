"""Routes for aggregated purchase history."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings
from app.constants.subscription_plans import SUBSCRIPTION_PLANS
from app.models.purchase_history import (
    PurchaseHistoryNote,
    PurchaseHistoryProduct,
    PurchaseHistoryResponse,
    PurchaseHistorySalon,
    PurchaseHistorySummary,
)
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/purchases", tags=["purchases"])
security = HTTPBearer()


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なトークンです",
        )
    return user_id


def _build_plan_index() -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for plan in SUBSCRIPTION_PLANS:
        if plan.subscription_plan_id:
            index[plan.subscription_plan_id] = {
                "label": plan.label,
                "points": plan.points,
                "usd_amount": plan.usd_amount,
            }
    return index


def _ensure_non_empty(sequence: Sequence[str]) -> List[str]:
    return [value for value in sequence if value]


@router.get("/history", response_model=PurchaseHistoryResponse)
async def get_purchase_history(
    product_limit: int = Query(20, ge=1, le=100, description="取得するLP購入履歴の最大件数"),
    note_limit: int = Query(20, ge=1, le=100, description="取得するNOTE購入履歴の最大件数"),
    salon_limit: int = Query(50, ge=1, le=200, description="取得するアクティブなサロン会員情報の最大件数"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    # Product purchases via point transactions
    product_query = (
        supabase
        .table("point_transactions")
        .select("id, related_product_id, amount, description, created_at", count="exact")
        .eq("user_id", user_id)
        .eq("transaction_type", "product_purchase")
        .order("created_at", desc=True)
        .range(0, product_limit - 1)
    )
    product_response = product_query.execute()
    product_rows = product_response.data or []
    product_total = getattr(product_response, "count", None) or len(product_rows)

    product_order_response = (
        supabase
        .table("payment_orders")
        .select("id, item_id, seller_id, amount_jpy, metadata, completed_at, updated_at, created_at, status, payment_method")
        .eq("user_id", user_id)
        .eq("item_type", "product")
        .eq("status", "COMPLETED")
        .order("completed_at", desc=True)
        .range(0, product_limit - 1)
        .execute()
    )
    product_orders = product_order_response.data or []
    product_total += len(product_orders)

    product_ids_set = {row.get("related_product_id") for row in product_rows if row.get("related_product_id")}
    product_ids_set.update({order.get("item_id") for order in product_orders if order.get("item_id")})
    product_ids = _ensure_non_empty(product_ids_set)
    product_map: Dict[str, dict] = {}
    seller_ids: List[str] = []
    lp_ids: List[str] = []

    if product_ids:
        products_data = (
            supabase
            .table("products")
            .select("id, title, seller_id, lp_id")
            .in_("id", product_ids)
            .execute()
        )
        for product in products_data.data or []:
            product_id = product.get("id")
            if product_id:
                product_map[product_id] = product
                seller_id = product.get("seller_id")
                if seller_id:
                    seller_ids.append(seller_id)
                lp_id = product.get("lp_id")
                if lp_id:
                    lp_ids.append(lp_id)

    for order in product_orders:
        seller_id = order.get("seller_id")
        if seller_id:
            seller_ids.append(seller_id)
        metadata = order.get("metadata")
        if isinstance(metadata, dict):
            lp_id = metadata.get("lp_id")
            if lp_id:
                lp_ids.append(lp_id)

    seller_map: Dict[str, dict] = {}
    if seller_ids:
        sellers_data = (
            supabase
            .table("users")
            .select("id, username, display_name, profile_image_url")
            .in_("id", _ensure_non_empty(set(seller_ids)))
            .execute()
        )
        for record in sellers_data.data or []:
            if record.get("id"):
                seller_map[record["id"]] = record

    lp_slug_map: Dict[str, Optional[str]] = {}
    if lp_ids:
        lp_response = (
            supabase
            .table("landing_pages")
            .select("id, slug")
            .in_("id", _ensure_non_empty(set(lp_ids)))
            .execute()
        )
        for lp in lp_response.data or []:
            if lp.get("id"):
                lp_slug_map[lp["id"]] = lp.get("slug")

    product_history: List[PurchaseHistoryProduct] = []
    for row in product_rows:
        related_product_id = row.get("related_product_id")
        product_info = product_map.get(related_product_id or "") if related_product_id else None
        seller_info = seller_map.get(product_info.get("seller_id")) if product_info else None
        lp_slug = lp_slug_map.get(product_info.get("lp_id")) if product_info else None
        amount = row.get("amount") or 0
        product_history.append(
            PurchaseHistoryProduct(
                transaction_id=row.get("id"),
                product_id=related_product_id,
                product_title=product_info.get("title") if product_info else None,
                amount_points=abs(int(amount)),
                amount_jpy=None,
                purchased_at=row.get("created_at"),
                description=row.get("description"),
                seller_username=seller_info.get("username") if seller_info else None,
                seller_display_name=seller_info.get("display_name") if seller_info else None,
                seller_profile_image_url=seller_info.get("profile_image_url") if seller_info else None,
                lp_slug=lp_slug,
                payment_method="points",
            )
        )

    for order in product_orders:
        product_id = order.get("item_id")
        product_info = product_map.get(product_id or "") if product_id else None
        seller_lookup_id = None
        if product_info and product_info.get("seller_id"):
            seller_lookup_id = product_info.get("seller_id")
        elif order.get("seller_id"):
            seller_lookup_id = order.get("seller_id")
        seller_info = seller_map.get(seller_lookup_id) if seller_lookup_id else None

        metadata = order.get("metadata")
        if not isinstance(metadata, dict):
            try:
                metadata = json.loads(metadata) if metadata else {}
            except json.JSONDecodeError:
                metadata = {}

        lp_slug = None
        if product_info and product_info.get("lp_id"):
            lp_slug = lp_slug_map.get(product_info.get("lp_id"))
        elif isinstance(metadata, dict):
            lp_id = metadata.get("lp_id")
            if lp_id:
                lp_slug = lp_slug_map.get(lp_id)

        amount_jpy = order.get("amount_jpy")
        purchased_at = order.get("completed_at") or order.get("updated_at") or order.get("created_at")
        description = metadata.get("description") if isinstance(metadata, dict) else None

        product_history.append(
            PurchaseHistoryProduct(
                transaction_id=order.get("id"),
                product_id=product_id,
                product_title=product_info.get("title") if product_info else None,
                amount_points=0,
                amount_jpy=int(amount_jpy) if amount_jpy is not None else None,
                purchased_at=purchased_at,
                description=description or "日本円決済で購入しました",
                seller_username=seller_info.get("username") if seller_info else None,
                seller_display_name=seller_info.get("display_name") if seller_info else None,
                seller_profile_image_url=seller_info.get("profile_image_url") if seller_info else None,
                lp_slug=lp_slug,
                payment_method=order.get("payment_method", "yen"),
            )
        )

    if product_history:
        product_history.sort(
            key=lambda record: record.purchased_at.timestamp() if isinstance(record.purchased_at, datetime) else float("-inf"),
            reverse=True,
        )
        product_history = product_history[:product_limit]

    # Note purchases
    note_query = (
        supabase
        .table("note_purchases")
        .select("id, note_id, points_spent, purchased_at", count="exact")
        .eq("buyer_id", user_id)
        .order("purchased_at", desc=True)
        .range(0, note_limit - 1)
    )
    note_response = note_query.execute()
    note_rows = note_response.data or []
    note_total = getattr(note_response, "count", None) or len(note_rows)

    note_order_response = (
        supabase
        .table("payment_orders")
        .select("id, item_id, amount_jpy, metadata, completed_at, updated_at, created_at, status, payment_method")
        .eq("user_id", user_id)
        .eq("item_type", "note")
        .eq("status", "COMPLETED")
        .order("completed_at", desc=True)
        .range(0, note_limit - 1)
        .execute()
    )
    note_orders = note_order_response.data or []
    note_total += len(note_orders)

    note_ids_set = {row.get("note_id") for row in note_rows if row.get("note_id")}
    note_ids_set.update({order.get("item_id") for order in note_orders if order.get("item_id")})
    note_ids = _ensure_non_empty(note_ids_set)
    note_map: Dict[str, dict] = {}
    author_ids: List[str] = []

    if note_ids:
        notes_data = (
            supabase
            .table("notes")
            .select("id, title, slug, cover_image_url, author_id")
            .in_("id", note_ids)
            .execute()
        )
        for record in notes_data.data or []:
            note_id = record.get("id")
            if note_id:
                note_map[note_id] = record
                author_id = record.get("author_id")
                if author_id:
                    author_ids.append(author_id)

    for order in note_orders:
        author_id = order.get("seller_id")
        if author_id:
            author_ids.append(author_id)

    author_map: Dict[str, dict] = {}
    if author_ids:
        authors_data = (
            supabase
            .table("users")
            .select("id, username, display_name")
            .in_("id", _ensure_non_empty(set(author_ids)))
            .execute()
        )
        for record in authors_data.data or []:
            if record.get("id"):
                author_map[record["id"]] = record

    note_history: List[PurchaseHistoryNote] = []
    for row in note_rows:
        note_id = row.get("note_id")
        note_info = note_map.get(note_id or "") if note_id else None
        author_info = author_map.get(note_info.get("author_id")) if note_info else None
        note_history.append(
            PurchaseHistoryNote(
                purchase_id=row.get("id"),
                note_id=note_id or "",
                note_title=note_info.get("title") if note_info else None,
                note_slug=note_info.get("slug") if note_info else None,
                cover_image_url=note_info.get("cover_image_url") if note_info else None,
                author_username=author_info.get("username") if author_info else None,
                author_display_name=author_info.get("display_name") if author_info else None,
                points_spent=int(row.get("points_spent") or 0),
                purchased_at=row.get("purchased_at"),
                amount_jpy=None,
                payment_method="points",
            )
        )

    for order in note_orders:
        note_id = order.get("item_id")
        note_info = note_map.get(note_id or "") if note_id else None
        author_id = order.get("seller_id") or (note_info.get("author_id") if note_info else None)
        author_info = author_map.get(author_id) if author_id else None

        metadata = order.get("metadata")
        if not isinstance(metadata, dict):
            try:
                metadata = json.loads(metadata) if metadata else {}
            except json.JSONDecodeError:
                metadata = {}

        amount_jpy = order.get("amount_jpy")
        purchased_at = order.get("completed_at") or order.get("updated_at") or order.get("created_at")

        note_history.append(
            PurchaseHistoryNote(
                purchase_id=order.get("id"),
                note_id=note_id or "",
                note_title=note_info.get("title") if note_info else None,
                note_slug=note_info.get("slug") if note_info else None,
                cover_image_url=note_info.get("cover_image_url") if note_info else None,
                author_username=author_info.get("username") if author_info else None,
                author_display_name=author_info.get("display_name") if author_info else None,
                points_spent=0,
                amount_jpy=int(amount_jpy) if amount_jpy is not None else None,
                purchased_at=purchased_at,
                payment_method=order.get("payment_method", "yen"),
            )
        )

    if note_history:
        note_history.sort(
            key=lambda record: record.purchased_at.timestamp() if isinstance(record.purchased_at, datetime) else float("-inf"),
            reverse=True,
        )
        note_history = note_history[:note_limit]

    # Active salon memberships
    membership_query = (
        supabase
        .table("salon_memberships")
        .select("id, salon_id, status, joined_at, last_charged_at, next_charge_at", count="exact")
        .eq("user_id", user_id)
        .in_("status", ["ACTIVE"])
        .order("joined_at", desc=True)
        .range(0, salon_limit - 1)
    )
    membership_response = membership_query.execute()
    membership_rows = membership_response.data or []
    membership_total = getattr(membership_response, "count", None) or len(membership_rows)

    salon_ids = _ensure_non_empty({row.get("salon_id") for row in membership_rows})
    salon_map: Dict[str, dict] = {}
    salon_owner_ids: List[str] = []

    if salon_ids:
        salons_data = (
            supabase
            .table("salons")
            .select("id, title, thumbnail_url, owner_id, subscription_plan_id")
            .in_("id", salon_ids)
            .execute()
        )
        for record in salons_data.data or []:
            salon_id = record.get("id")
            if salon_id:
                salon_map[salon_id] = record
                owner_id = record.get("owner_id")
                if owner_id:
                    salon_owner_ids.append(owner_id)

    owner_map: Dict[str, dict] = {}
    if salon_owner_ids:
        owners_data = (
            supabase
            .table("users")
            .select("id, username, display_name")
            .in_("id", _ensure_non_empty(set(salon_owner_ids)))
            .execute()
        )
        for record in owners_data.data or []:
            if record.get("id"):
                owner_map[record["id"]] = record

    plan_index = _build_plan_index()

    salon_history: List[PurchaseHistorySalon] = []
    for row in membership_rows:
        salon_id = row.get("salon_id")
        salon_info = salon_map.get(salon_id or "") if salon_id else None
        owner_info = owner_map.get(salon_info.get("owner_id")) if salon_info else None
        plan_meta: Optional[dict] = None
        if salon_info and salon_info.get("subscription_plan_id"):
            plan_meta = plan_index.get(salon_info["subscription_plan_id"])
        status_value = str(row.get("status") or "").upper()
        salon_history.append(
            PurchaseHistorySalon(
                membership_id=row.get("id"),
                salon_id=salon_id or "",
                salon_title=salon_info.get("title") if salon_info else None,
                salon_category=None,
                salon_thumbnail_url=salon_info.get("thumbnail_url") if salon_info else None,
                owner_username=owner_info.get("username") if owner_info else None,
                owner_display_name=owner_info.get("display_name") if owner_info else None,
                plan_label=plan_meta.get("label") if plan_meta else None,
                plan_points=plan_meta.get("points") if plan_meta else None,
                plan_usd_amount=plan_meta.get("usd_amount") if plan_meta else None,
                joined_at=row.get("joined_at"),
                status=status_value,
                next_charge_at=row.get("next_charge_at"),
                last_charged_at=row.get("last_charged_at"),
            )
        )

    summary = PurchaseHistorySummary(
        product_purchases=product_total,
        note_purchases=note_total,
        active_salon_memberships=membership_total,
    )

    return PurchaseHistoryResponse(
        summary=summary,
        products=product_history,
        notes=note_history,
        active_salons=salon_history,
    )
