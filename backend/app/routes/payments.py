from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any, Dict, Optional

import logging
from urllib.parse import urlencode

from app.constants.subscription_plans import get_subscription_plan
from app.models.payments import QuickCheckoutRequest, QuickCheckoutResponse
from app.services.billing_profiles import build_payer_details
from app.services.one_lat import one_lat_client
from app.services.platform_settings import get_platform_settings
from app.utils.locale import locale_path_prefix, normalize_locale

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings
from app.models.billing_profile import BillingProfilePayload, BillingProfileRecord, BillingProfileResponse
from app.services.billing_profiles import load_billing_profile
from app.utils.auth import decode_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])
security = HTTPBearer(auto_error=False)


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def get_current_user_id(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証情報が提供されていません")

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except Exception:  # pragma: no cover - token decode errors handled uniformly
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="トークンの検証に失敗しました") from None

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")
    return user_id


def _normalize_upsert_payload(user_id: str, payload: BillingProfilePayload) -> Dict[str, Any]:
    record = payload.model_dump(exclude_unset=True)
    record["user_id"] = user_id
    record.setdefault("country_code", "JP")
    if record.get("country_code"):
        record["country_code"] = str(record["country_code"]).upper()
    record["updated_at"] = datetime.utcnow().isoformat()
    return record


def _map_record(row: Dict[str, Any], user_id: str) -> BillingProfileResponse:
    profile = BillingProfileRecord.model_validate(row)
    profile_payload = BillingProfilePayload.model_validate(
        profile.model_dump(exclude={"created_at", "updated_at"})
    )
    return BillingProfileResponse(
        user_id=user_id,
        profile=profile_payload,
        updated_at=profile.updated_at,
    )


def _require_billing_profile(supabase: Client, user_id: str) -> Dict[str, Any]:
    profile = load_billing_profile(supabase, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="請求先情報を設定してください")
    return profile


def _get_effective_exchange_rate() -> float:
    platform_settings = get_platform_settings()
    effective_rate = platform_settings.effective_exchange_rate
    if effective_rate <= 0:
        fallback = settings.default_exchange_rate_usd_jpy + settings.default_exchange_spread_jpy
        return max(fallback, 0.01)
    return effective_rate


def _convert_jpy_to_usd(amount_jpy: float) -> float:
    rate = _get_effective_exchange_rate()
    return round(amount_jpy / rate, 2)


@router.get("/billing-profile", response_model=BillingProfileResponse)
async def get_billing_profile(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    try:
        response = (
            supabase
            .table("billing_profiles")
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:  # pragma: no cover - Supabase connectivity
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="請求先情報の取得に失敗しました") from exc

    row = response.data if response else None
    if not row:
        return BillingProfileResponse(user_id=user_id, profile=None, updated_at=None)

    return _map_record(row, user_id)


@router.put("/billing-profile", response_model=BillingProfileResponse)
async def upsert_billing_profile(
    payload: BillingProfilePayload,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    upsert_payload = _normalize_upsert_payload(user_id, payload)
    try:
        response = (
            supabase
            .table("billing_profiles")
            .upsert(upsert_payload, on_conflict="user_id")
            .execute()
        )
    except Exception as exc:  # pragma: no cover - Supabase error propagation
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="請求先情報の保存に失敗しました") from exc

    if response.data:
        row = response.data[0]
    else:  # Supabase sometimes returns empty data on update; refetch to ensure consistency
        try:
            fetch = (
                supabase
                .table("billing_profiles")
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="請求先情報の保存に失敗しました") from exc
        row = fetch.data if fetch else None
        if not row:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="請求先情報の保存に失敗しました")

    return _map_record(row, user_id)


@router.delete("/billing-profile", status_code=status.HTTP_204_NO_CONTENT)
async def delete_billing_profile(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    try:
        supabase.table("billing_profiles").delete().eq("user_id", user_id).execute()
    except Exception as exc:  # pragma: no cover - Supabase error propagation
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="請求先情報の削除に失敗しました") from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _prepare_note_checkout(
    supabase: Client,
    user_id: str,
    user_record: Dict[str, Any],
    note_id: str,
    locale: Optional[str],
    payer_details: Dict[str, Optional[str]],
) -> QuickCheckoutResponse:
    note_response = (
        supabase
        .table("notes")
        .select("id, author_id, slug, title, price_jpy, allow_jpy_purchase")
        .eq("id", note_id)
        .single()
        .execute()
    )
    if not note_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note = note_response.data
    if not note.get("allow_jpy_purchase"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="このNOTEは日本円決済に対応していません")

    price_jpy = note.get("price_jpy")
    if price_jpy is None or price_jpy <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="price_jpy が設定されていません")

    amount_jpy = int(price_jpy)
    amount_usd = _convert_jpy_to_usd(amount_jpy)
    external_id = f"note_quick_{note_id}_{uuid.uuid4().hex[:8]}"

    backend_url = settings.backend_public_url.rstrip("/")
    frontend_url = settings.frontend_url.rstrip("/")
    webhook_url = f"{backend_url}/api/webhooks/one-lat"
    requested_locale = normalize_locale(locale) if locale else normalize_locale(user_record.get("preferred_locale"))
    locale_prefix = locale_path_prefix(requested_locale)
    slug = note.get("slug")
    success_path = f"{locale_prefix}/notes/{slug}/purchase/success" if slug else f"{locale_prefix}/notes/purchase/success"
    error_path = f"{locale_prefix}/notes/{slug}/purchase/error" if slug else f"{locale_prefix}/notes/purchase/error"
    success_url = f"{frontend_url}{success_path}?external_id={external_id}"
    error_url = f"{frontend_url}{error_path}?external_id={external_id}"

    checkout_data = await one_lat_client.create_checkout_preference(
        amount=amount_usd,
        currency="USD",
        title=f"Note Purchase - {note.get('title', 'NOTE')}",
        external_id=external_id,
        webhook_url=webhook_url,
        success_url=success_url,
        error_url=error_url,
        payer_email=payer_details.get("email"),
        payer_name=payer_details.get("first_name"),
        payer_last_name=payer_details.get("last_name"),
        payer_phone=payer_details.get("phone_number"),
    )

    metadata = {
        "note_slug": slug,
        "note_title": note.get("title"),
        "author_id": note.get("author_id"),
        "locale": requested_locale,
        "quick_checkout": True,
    }

    order_payload = {
        "user_id": user_id,
        "seller_id": note.get("author_id"),
        "item_type": "note",
        "item_id": note_id,
        "payment_method": "yen",
        "currency": "JPY",
        "amount_jpy": amount_jpy,
        "tax_amount_jpy": 0,
        "status": "PENDING",
        "external_id": external_id,
        "checkout_preference_id": checkout_data.get("id"),
        "metadata": metadata,
    }

    try:
        supabase.table("payment_orders").insert(order_payload).execute()
    except Exception as exc:
        logger.exception("Failed to record payment order for note", extra={"user_id": user_id, "note_id": note_id})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="決済情報の保存に失敗しました") from exc

    return QuickCheckoutResponse(
        checkout_url=checkout_data.get("checkout_url"),
        external_id=external_id,
        item_type="note",
    )


async def _prepare_product_checkout(
    supabase: Client,
    user_id: str,
    user_record: Dict[str, Any],
    product_id: str,
    quantity: int,
    payer_details: Dict[str, Optional[str]],
) -> QuickCheckoutResponse:
    product_response = (
        supabase
        .table("products")
        .select("id, title, seller_id, price_jpy, allow_jpy_purchase, stock_quantity")
        .eq("id", product_id)
        .single()
        .execute()
    )
    if not product_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    product = product_response.data
    if not product.get("allow_jpy_purchase"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="この商品は日本円決済に対応していません")

    stock_quantity = product.get("stock_quantity")
    if isinstance(stock_quantity, int) and stock_quantity >= 0 and quantity > stock_quantity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="在庫不足です")

    price_jpy = product.get("price_jpy")
    if price_jpy is None or price_jpy <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="price_jpy が設定されていません")

    amount_jpy = int(price_jpy) * quantity
    amount_usd = _convert_jpy_to_usd(amount_jpy)
    external_id = f"product_quick_{product_id}_{uuid.uuid4().hex[:8]}"

    backend_url = settings.backend_public_url.rstrip("/")
    frontend_url = settings.frontend_url.rstrip("/")
    webhook_url = f"{backend_url}/api/webhooks/one-lat"
    success_url = f"{frontend_url}/orders/complete?external_id={external_id}"
    error_url = f"{frontend_url}/orders/error?external_id={external_id}"

    checkout_data = await one_lat_client.create_checkout_preference(
        amount=amount_usd,
        currency="USD",
        title=f"Product Purchase - {product.get('title', 'Product')}",
        external_id=external_id,
        webhook_url=webhook_url,
        success_url=success_url,
        error_url=error_url,
        payer_email=payer_details.get("email"),
        payer_name=payer_details.get("first_name"),
        payer_last_name=payer_details.get("last_name"),
        payer_phone=payer_details.get("phone_number"),
    )

    metadata = {
        "quantity": quantity,
        "unit_price_jpy": product.get("price_jpy"),
        "quick_checkout": True,
    }

    order_payload = {
        "user_id": user_id,
        "seller_id": product.get("seller_id"),
        "item_type": "product",
        "item_id": product_id,
        "payment_method": "yen",
        "currency": "JPY",
        "amount_jpy": amount_jpy,
        "tax_amount_jpy": 0,
        "status": "PENDING",
        "external_id": external_id,
        "checkout_preference_id": checkout_data.get("id"),
        "metadata": metadata,
    }

    try:
        supabase.table("payment_orders").insert(order_payload).execute()
    except Exception as exc:
        logger.exception("Failed to record payment order for product", extra={"user_id": user_id, "product_id": product_id})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="決済情報の保存に失敗しました") from exc

    return QuickCheckoutResponse(
        checkout_url=checkout_data.get("checkout_url"),
        external_id=external_id,
        item_type="product",
    )


async def _prepare_subscription_checkout(
    supabase: Client,
    user_id: str,
    user_record: Dict[str, Any],
    payload: QuickCheckoutRequest,
    payer_details: Dict[str, Optional[str]],
) -> QuickCheckoutResponse:
    assert payload.plan_key is not None  # validated upstream
    plan = get_subscription_plan(payload.plan_key)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サブスクプランが見つかりません")

    external_id = f"subscription_quick_{plan.key}_{uuid.uuid4().hex[:8]}"
    success_params = {
        "status": "success",
        "external_id": external_id,
        "plan": plan.key,
    }
    if payload.locale:
        success_params["locale"] = payload.locale
    error_params = {"status": "error", "external_id": external_id}

    def _build_frontend_url(path: Optional[str], default_path: str, params: Dict[str, str]) -> str:
        base_url = settings.frontend_url.rstrip("/")
        normalized_path = path or default_path
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        query = urlencode(params)
        return f"{base_url}{normalized_path}?{query}" if query else f"{base_url}{normalized_path}"

    success_url = _build_frontend_url(payload.success_path, "/subscription/result", success_params)
    error_url = _build_frontend_url(payload.error_path, "/subscription/result", error_params)
    webhook_url = f"{settings.backend_public_url.rstrip('/')}/api/webhooks/one-lat"

    checkout_data = await one_lat_client.create_checkout_preference(
        amount=plan.usd_amount,
        currency="USD",
        title=f"Subscription - {plan.points} points",
        external_id=external_id,
        webhook_url=webhook_url,
        success_url=success_url,
        error_url=error_url,
        payer_email=payer_details.get("email"),
        payer_name=payer_details.get("first_name"),
        payer_last_name=payer_details.get("last_name"),
        payer_phone=payer_details.get("phone_number"),
        preference_type="SUBSCRIPTION",
        payment_link_id=plan.subscription_plan_id,
        expiration_minutes=30,
    )

    session_metadata = {k: v for k, v in payload.model_dump(exclude_none=True).items() if k not in {"item_type", "item_id", "quantity"}}
    if payload.seller_username:
        session_metadata.setdefault("seller_username", payload.seller_username)
    session_metadata.update({"quick_checkout": True})

    session_record = {
        "user_id": user_id,
        "plan_key": plan.key,
        "external_id": external_id,
        "checkout_preference_id": checkout_data.get("id"),
        "status": "PENDING",
        "metadata": session_metadata,
        "seller_id": payload.seller_id,
    }

    try:
        supabase.table("subscription_sessions").insert(session_record).execute()
    except Exception as exc:
        logger.exception("Failed to create subscription session", extra={"user_id": user_id, "plan_key": plan.key})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="サブスク決済の準備に失敗しました") from exc

    return QuickCheckoutResponse(
        checkout_url=checkout_data.get("checkout_url"),
        external_id=external_id,
        item_type="subscription",
    )


@router.post("/quick-checkout", response_model=QuickCheckoutResponse)
async def create_quick_checkout(
    request: QuickCheckoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    billing_profile = _require_billing_profile(supabase, user_id)

    user_resp = (
        supabase
        .table("users")
        .select("email, username, preferred_locale")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not user_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    user_record = user_resp.data
    payer_details = build_payer_details(user_record, billing_profile)

    try:
        if request.item_type == "note":
            assert request.item_id is not None
            return await _prepare_note_checkout(
                supabase,
                user_id,
                user_record,
                request.item_id,
                request.locale,
                payer_details,
            )
        if request.item_type == "product":
            assert request.item_id is not None
            quantity = request.quantity or 1
            return await _prepare_product_checkout(
                supabase,
                user_id,
                user_record,
                request.item_id,
                quantity,
                payer_details,
            )
        if request.item_type == "subscription":
            return await _prepare_subscription_checkout(
                supabase,
                user_id,
                user_record,
                request,
                payer_details,
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to create quick checkout", extra={"user_id": user_id, "request": request.model_dump()})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="クイック決済の準備に失敗しました") from exc

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="サポートされていないクイック決済です")
