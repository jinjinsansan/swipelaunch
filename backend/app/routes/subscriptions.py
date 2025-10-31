"""Subscription management endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client, settings
from app.constants.subscription_plans import (
    SUBSCRIPTION_PLANS,
    get_subscription_plan,
)
from app.models.subscriptions import (
    SubscriptionCancelResponse,
    SubscriptionCheckoutRequest,
    SubscriptionCheckoutResponse,
    SubscriptionPlanListResponse,
    SubscriptionPlanResponse,
    UserSubscriptionListResponse,
    UserSubscriptionResponse,
)
from app.services.one_lat import one_lat_client
from app.utils.auth import decode_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
security = HTTPBearer()


def _get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです",
            )
        return user_id
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました",
        ) from exc


def _build_frontend_url(path: Optional[str], default_path: str, params: Dict[str, str]) -> str:
    base_url = settings.frontend_url.rstrip("/")
    normalized_path = path or default_path
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"

    query = urlencode({k: v for k, v in params.items() if v is not None})
    if query:
        return f"{base_url}{normalized_path}?{query}"
    return f"{base_url}{normalized_path}"


@router.get("/plans", response_model=SubscriptionPlanListResponse)
async def list_subscription_plans(_: HTTPAuthorizationCredentials = Depends(security)) -> SubscriptionPlanListResponse:
    """Return available subscription plans."""

    plans = [
        SubscriptionPlanResponse(
            plan_key=plan.key,
            label=plan.label,
            points=plan.points,
            usd_amount=plan.usd_amount,
            subscription_plan_id=plan.subscription_plan_id,
        )
        for plan in SUBSCRIPTION_PLANS
    ]
    return SubscriptionPlanListResponse(data=plans)


@router.post("/checkout", response_model=SubscriptionCheckoutResponse)
async def create_subscription_checkout(
    payload: SubscriptionCheckoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SubscriptionCheckoutResponse:
    """Create a ONE.lat subscription checkout preference for the given plan."""

    user_id = _get_current_user_id(credentials)
    plan = get_subscription_plan(payload.plan_key)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたプランが見つかりません")

    supabase = get_supabase_client()

    salon_id: Optional[str] = None
    if payload.salon_id:
        salon_response = (
            supabase.table("salons")
            .select("id, owner_id, subscription_plan_id")
            .eq("id", payload.salon_id)
            .single()
            .execute()
        )
        if not salon_response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")

        salon_record = salon_response.data
        if salon_record.get("subscription_plan_id") != plan.subscription_plan_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="サロンに設定されたプランと選択したプランが一致しません",
            )
        if payload.seller_id and payload.seller_id != salon_record.get("owner_id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="サロンと販売者情報が一致しません",
            )
        salon_id = salon_record.get("id")

    user_response = (
        supabase.table("users").select("email, username").eq("id", user_id).single().execute()
    )
    if not user_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    user = user_response.data

    external_id = f"subscription_{plan.key}_{user_id}_{uuid.uuid4().hex[:8]}"

    success_params = {
        "status": "success",
        "plan": plan.key,
        "external_id": external_id,
        "seller": payload.seller_username,
        "seller_id": payload.seller_id,
    }
    error_params = {
        "status": "error",
        "plan": plan.key,
        "external_id": external_id,
        "seller": payload.seller_username,
        "seller_id": payload.seller_id,
    }

    success_url = _build_frontend_url(payload.success_path, "/subscription/result", success_params)
    error_url = _build_frontend_url(payload.error_path, "/subscription/result", error_params)
    webhook_url = f"{settings.backend_public_url.rstrip('/')}/api/webhooks/one-lat"

    logger.info(
        "Creating subscription checkout",
        extra={
            "user_id": user_id,
            "plan_key": plan.key,
            "external_id": external_id,
            "seller_username": payload.seller_username,
        },
    )

    checkout_data = await one_lat_client.create_checkout_preference(
        amount=plan.usd_amount,
        currency="USD",
        title=f"Subscription - {plan.points} points",
        external_id=external_id,
        webhook_url=webhook_url,
        success_url=success_url,
        error_url=error_url,
        payer_email=user.get("email"),
        payer_name=user.get("username"),
        preference_type="SUBSCRIPTION",
        payment_link_id=plan.subscription_plan_id,
        expiration_minutes=30,
    )

    metadata = dict(payload.metadata or {})
    if salon_id:
        metadata.setdefault("salon_id", salon_id)

    session_record = {
        "user_id": user_id,
        "plan_key": plan.key,
        "subscription_plan_id": plan.subscription_plan_id,
        "points_per_cycle": plan.points,
        "usd_amount": plan.usd_amount,
        "checkout_preference_id": checkout_data.get("id"),
        "external_id": external_id,
        "status": "PENDING",
        "seller_id": payload.seller_id,
        "seller_username": payload.seller_username,
        "success_url": success_url,
        "error_url": error_url,
        "salon_id": salon_id,
        "metadata": metadata,
    }

    supabase.table("one_lat_subscription_sessions").insert(session_record).execute()

    return SubscriptionCheckoutResponse(
        checkout_url=checkout_data.get("checkout_url"),
        checkout_preference_id=checkout_data.get("id"),
        external_id=external_id,
    )


@router.get("", response_model=UserSubscriptionListResponse)
async def list_user_subscriptions(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserSubscriptionListResponse:
    user_id = _get_current_user_id(credentials)
    supabase = get_supabase_client()

    response = (
        supabase.table("user_subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    subscriptions = []
    for row in response.data or []:
        plan = get_subscription_plan(row.get("plan_key", ""))
        if not plan:
            # Skip unknown plans but log for debugging
            logger.warning("Unknown subscription plan encountered", extra={"row": row})
            continue

        cancelable = str(row.get("status", "")).upper() not in {"CANCELED", "EXPIRED", "REJECTED"}
        subscriptions.append(
            UserSubscriptionResponse(
                id=row.get("id"),
                plan_key=plan.key,
                label=plan.label,
                status=row.get("status"),
                points_per_cycle=plan.points,
                usd_amount=plan.usd_amount,
                subscription_plan_id=plan.subscription_plan_id,
                recurrent_payment_id=row.get("recurrent_payment_id"),
                next_charge_at=row.get("next_charge_at"),
                last_charge_at=row.get("last_charge_at"),
                last_event_type=row.get("last_event_type"),
                seller_id=row.get("seller_id"),
                seller_username=row.get("seller_username"),
                salon_id=row.get("salon_id"),
                metadata=row.get("metadata"),
                cancelable=cancelable,
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )

    return UserSubscriptionListResponse(data=subscriptions)


@router.post("/{subscription_id}/cancel", response_model=SubscriptionCancelResponse)
async def cancel_subscription(
    subscription_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SubscriptionCancelResponse:
    user_id = _get_current_user_id(credentials)
    supabase = get_supabase_client()

    response = (
        supabase.table("user_subscriptions")
        .select("*")
        .eq("id", subscription_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サブスクリプションが見つかりません")

    record = response.data
    if not record.get("recurrent_payment_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="キャンセル可能な状態ではありません")

    if str(record.get("status", "")).upper() in {"CANCELED", "EXPIRED"}:
        canceled_at = datetime.now(timezone.utc)
        return SubscriptionCancelResponse(id=record.get("id"), status=record.get("status"), canceled_at=canceled_at)

    recurrent_payment_id = record.get("recurrent_payment_id")

    await one_lat_client.cancel_recurrent_payment(recurrent_payment_id=recurrent_payment_id)

    canceled_at = datetime.now(timezone.utc)
    update_payload = {
        "status": "CANCELED",
        "updated_at": canceled_at.isoformat(),
        "last_event_type": "RECURRENT_PAYMENT.CANCELLED",
        "last_event_at": canceled_at.isoformat(),
    }

    supabase.table("user_subscriptions").update(update_payload).eq("id", record["id"]).execute()

    supabase.table("one_lat_subscription_sessions").update({"status": "CANCELED"}).eq(
        "recurrent_payment_id", recurrent_payment_id
    ).execute()

    return SubscriptionCancelResponse(id=record.get("id"), status="CANCELED", canceled_at=canceled_at)
