from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings
from app.models.payment_method import (
    ConfirmPaymentMethodRequest,
    InitiatePaymentMethodResponse,
    PaymentMethodListResponse,
    PaymentMethodSummary,
    SetDefaultPaymentMethodRequest,
)
from app.services.one_lat import one_lat_client
from app.utils.auth import decode_access_token
from app.utils.payment_methods import load_payment_method_or_404, map_payment_method_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment-methods", tags=["payment_methods"])
security = HTTPBearer()


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        user_id = payload.get("sub")
    except Exception as exc:  # pragma: no cover - auth guard
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証情報が無効です") from exc

    if not isinstance(user_id, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証情報が無効です")

    return user_id


def _ensure_external_id_matches_user(external_id: str, user_id: str) -> None:
    prefix = f"pm_setup_{user_id}_"
    if not external_id.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="支払い方法登録リクエストが不正です")


def _ensure_user_email(supabase: Client, user_id: str) -> Dict[str, Any]:
    response = (
        supabase
        .table("users")
        .select("email, username")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    user = response.data if response else None
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")
    if not user.get("email"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="メールアドレスが登録されていません")
    return user


def _map_to_pydantic(row: Dict[str, Any]) -> PaymentMethodSummary:
    mapped = map_payment_method_summary(row)
    return PaymentMethodSummary(**mapped)


def _extract_payment_method(data: Any) -> Optional[Dict[str, Any]]:
    if isinstance(data, dict):
        candidate = data.get("payment_method") or data.get("paymentMethod")
        if isinstance(candidate, dict):
            return candidate

        for list_key in (
            "payment_methods",
            "paymentMethods",
            "payer_payment_methods",
            "payerPaymentMethods",
        ):
            list_value = data.get(list_key)
            if isinstance(list_value, list):
                for item in list_value:
                    extracted = _extract_payment_method(item)
                    if extracted:
                        return extracted
            elif isinstance(list_value, dict):
                extracted = _extract_payment_method(list_value)
                if extracted:
                    return extracted

        for key in (
            "payments",
            "payment_orders",
            "paymentOrders",
            "charges",
            "transactions",
            "results",
            "items",
        ):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    extracted = _extract_payment_method(item)
                    if extracted:
                        return extracted
            elif isinstance(value, dict):
                extracted = _extract_payment_method(value)
                if extracted:
                    return extracted
    elif isinstance(data, list):
        for entry in data:
            extracted = _extract_payment_method(entry)
            if extracted:
                return extracted
    return None


@router.get("", response_model=PaymentMethodListResponse)
async def list_payment_methods(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    try:
        response = (
            supabase
            .table("one_lat_payment_methods")
            .select("*")
            .eq("user_id", user_id)
            .order("is_default", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の取得に失敗しました") from exc

    rows = response.data or []
    summaries = [_map_to_pydantic(row) for row in rows if not row.get("revoked_at")]
    return PaymentMethodListResponse(items=summaries)


@router.post("/one-lat/initiate", response_model=InitiatePaymentMethodResponse)
async def initiate_one_lat_payment_method(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    user = _ensure_user_email(supabase, user_id)

    external_id = f"pm_setup_{user_id}_{uuid.uuid4().hex[:10]}"
    backend_url = settings.backend_public_url.rstrip("/")
    frontend_url = settings.frontend_url.rstrip("/")

    success_url = f"{frontend_url}/points/payment-methods/success?external_id={external_id}"
    error_url = f"{frontend_url}/points/payment-methods/error?external_id={external_id}"

    try:
        checkout_data = await one_lat_client.create_checkout_preference(
            amount=1.00,
            currency="USD",
            title="Payment method setup",
            external_id=external_id,
            webhook_url=f"{backend_url}/api/webhooks/one-lat",
            success_url=success_url,
            error_url=error_url,
            payer_email=user.get("email"),
            payer_name=user.get("username"),
            preference_type="PAYMENT",
            metadata={"purpose": "payment_method_setup"},
        )
    except Exception as exc:  # pragma: no cover - depends on external API
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="決済事業者でエラーが発生しました") from exc

    checkout_url = checkout_data.get("checkout_url")
    checkout_preference_id = checkout_data.get("id")
    if not checkout_url or not checkout_preference_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="決済事業者からのレスポンスが不正です")

    return InitiatePaymentMethodResponse(
        checkout_url=checkout_url,
        checkout_preference_id=checkout_preference_id,
        external_id=external_id,
    )


@router.post("/one-lat/confirm", response_model=PaymentMethodSummary)
async def confirm_one_lat_payment_method(
    payload: ConfirmPaymentMethodRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    _ensure_external_id_matches_user(payload.external_id, user_id)
    supabase = get_supabase()

    try:
        preference = await one_lat_client.get_checkout_preference(payload.checkout_preference_id)
    except Exception as exc:  # pragma: no cover - depends on external API
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="決済事業者から情報を取得できませんでした") from exc

    if not isinstance(preference, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="決済情報が見つかりませんでした")

    if preference.get("external_id") != payload.external_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="支払い方法登録リクエストと照合できません")

    customer_info = preference.get("customer") or {}
    method_info = preference.get("payment_method") or (preference.get("payer") or {}).get("payment_method")

    # ONE.latのレスポンス仕様変更・遅延に備えて多段で取得を試みる
    if not isinstance(method_info, dict):
        method_info = _extract_payment_method(preference)

    payment_order_id: Optional[str] = None
    if isinstance(preference.get("payment_order_id"), str):
        payment_order_id = preference.get("payment_order_id")
    elif isinstance(preference.get("payment_order"), dict):
        payment_order_id = preference["payment_order"].get("id")
        customer_info = preference["payment_order"].get("customer") or customer_info
        if not isinstance(method_info, dict):
            method_info = _extract_payment_method(preference["payment_order"])
    elif isinstance(preference.get("metadata"), dict):
        payment_order_id = preference["metadata"].get("payment_order_id") or preference["metadata"].get("paymentOrderId")

    if not isinstance(method_info, dict) and payment_order_id:
        try:
            order_payload = await one_lat_client.get_payment_order(payment_order_id)
            customer_info = (order_payload.get("customer") or customer_info) if isinstance(order_payload, dict) else customer_info
            method_info = _extract_payment_method(order_payload)
        except Exception as exc:
            logger.warning("Failed to fetch payment order for payment method setup", extra={"payment_order_id": payment_order_id, "error": str(exc)})

    if not isinstance(method_info, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="支払い方法が確定していません")

    if isinstance(method_info.get("payment_method"), dict):
        method_info = method_info["payment_method"]

    customer_id = (
        method_info.get("customer_id")
        or (method_info.get("customer") or {}).get("id")
        or customer_info.get("id")
        or (preference.get("metadata") or {}).get("customer_id")
    )
    payment_method_id = (
        method_info.get("id")
        or method_info.get("payment_method_id")
        or (method_info.get("card") or {}).get("id")
        or (method_info.get("payment_method") or {}).get("id")
    )
    if not customer_id or not payment_method_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="支払い方法を特定できません")

    brand = (
        method_info.get("brand")
        or method_info.get("card_brand")
        or (method_info.get("card") or {}).get("brand")
        or (method_info.get("card") or {}).get("card_brand")
    )
    last4 = (
        method_info.get("last4")
        or method_info.get("card_last4")
        or (method_info.get("card") or {}).get("last4")
        or (method_info.get("card") or {}).get("last_four_digits")
    )
    exp_month = (
        method_info.get("exp_month")
        or method_info.get("card_exp_month")
        or (method_info.get("card") or {}).get("exp_month")
    )
    exp_year = (
        method_info.get("exp_year")
        or method_info.get("card_exp_year")
        or (method_info.get("card") or {}).get("exp_year")
    )
    brand_label = (
        method_info.get("brand_label")
        or method_info.get("display_name")
        or (method_info.get("card") or {}).get("display_name")
    )

    metadata = {
        "source_checkout_preference_id": payload.checkout_preference_id,
        "brand_label": brand_label,
        "raw": method_info,
    }

    try:
        existing = (
            supabase
            .table("one_lat_payment_methods")
            .select("*")
            .eq("user_id", user_id)
            .eq("payment_method_id", payment_method_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の保存に失敗しました") from exc

    is_default = False

    if existing and existing.data:
        record_id = existing.data["id"]
        try:
            update_payload = {
                "one_lat_customer_id": customer_id,
                "brand": brand,
                "last4": last4,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "metadata": metadata,
                "revoked_at": None,
            }
            supabase.table("one_lat_payment_methods").update(update_payload).eq("id", record_id).execute()
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の更新に失敗しました") from exc

        refreshed = load_payment_method_or_404(supabase, user_id=user_id, record_id=record_id, include_revoked=True)
        return _map_to_pydantic(refreshed)

    # Determine default status
    try:
        existing_methods = (
            supabase
            .table("one_lat_payment_methods")
            .select("id")
            .eq("user_id", user_id)
            .eq("revoked_at", None)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の保存に失敗しました") from exc

    if not existing_methods.data:
        is_default = True

    insert_payload = {
        "user_id": user_id,
        "one_lat_customer_id": customer_id,
        "payment_method_id": payment_method_id,
        "brand": brand,
        "last4": last4,
        "exp_month": exp_month,
        "exp_year": exp_year,
        "is_default": is_default,
        "metadata": metadata,
    }

    try:
        insert_response = supabase.table("one_lat_payment_methods").insert(insert_payload).execute()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の保存に失敗しました") from exc

    row = insert_response.data[0]
    return _map_to_pydantic(row)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(
    record_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    load_payment_method_or_404(supabase, user_id=user_id, record_id=record_id, include_revoked=True)

    try:
        supabase.table("one_lat_payment_methods").update({
            "revoked_at": datetime.now(timezone.utc).isoformat(),
            "is_default": False,
        }).eq("id", record_id).eq("user_id", user_id).execute()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の削除に失敗しました") from exc

    return None


@router.post("/{record_id}/default", response_model=PaymentMethodSummary)
async def set_default_payment_method(
    record_id: str,
    payload: SetDefaultPaymentMethodRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not payload.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="is_default は true を指定してください")

    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    load_payment_method_or_404(supabase, user_id=user_id, record_id=record_id)

    try:
        supabase.table("one_lat_payment_methods").update({
            "is_default": True,
        }).eq("id", record_id).eq("user_id", user_id).execute()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="支払い方法の更新に失敗しました") from exc

    refreshed = load_payment_method_or_404(supabase, user_id=user_id, record_id=record_id)
    return _map_to_pydantic(refreshed)
