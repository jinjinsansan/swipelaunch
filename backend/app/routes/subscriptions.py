"""Subscription management endpoints."""

from __future__ import annotations

import logging
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client, settings
from app.constants.subscription_plans import (
    SUBSCRIPTION_PLANS,
    get_subscription_plan,
    get_subscription_plan_by_id,
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
from app.services.purchase_notifications import (
    send_purchase_notification,
    send_seller_purchase_notification,
)
from app.utils.auth import decode_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
security = HTTPBearer()


def _ensure_metadata_dict(raw: Optional[Any]) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:  # pragma: no cover - defensive
            return {}
    return {}



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


@router.get("/session-status")
async def get_subscription_session_status(
    external_id: str = Query(..., min_length=8, max_length=255),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = _get_current_user_id(credentials)
    supabase = get_supabase_client()

    session_resp = (
        supabase
        .table("one_lat_subscription_sessions")
        .select(
            "id, user_id, plan_key, subscription_plan_id, status, last_event_type, last_event_at, metadata, seller_id, seller_username, salon_id"
        )
        .eq("external_id", external_id)
        .maybe_single()
        .execute()
    )

    session = session_resp.data if session_resp else None
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="セッションが見つかりません")

    if session.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="権限がありません")

    session_metadata = _ensure_metadata_dict(session.get("metadata"))
    notification_sent = bool(session_metadata.get("purchase_notification_sent"))

    plan = None
    if session.get("plan_key"):
        plan = get_subscription_plan(session["plan_key"])
    if not plan and session.get("subscription_plan_id"):
        plan = get_subscription_plan_by_id(session["subscription_plan_id"])

    subscription_resp = (
        supabase
        .table("user_subscriptions")
        .select(
            "id, status, last_event_type, last_event_at, metadata, recurrent_payment_id, seller_id, seller_username, salon_id"
        )
        .eq("external_id", external_id)
        .maybe_single()
        .execute()
    )
    subscription = subscription_resp.data if subscription_resp else None

    subscription_metadata = _ensure_metadata_dict(subscription.get("metadata")) if subscription else {}
    if subscription_metadata.get("purchase_notification_sent"):
        notification_sent = True

    salon_id: Optional[str] = (
        session.get("salon_id")
        or subscription_metadata.get("salon_id")
        or session_metadata.get("salon_id")
    )

    salon_info: Optional[Dict[str, Any]] = None
    if salon_id:
        salon_resp = (
            supabase
            .table("salons")
            .select("id, title, owner_id")
            .eq("id", salon_id)
            .maybe_single()
            .execute()
        )
        salon_info = salon_resp.data if salon_resp else None

    membership_resp = None
    membership_status: Optional[str] = None
    if salon_id:
        membership_resp = (
            supabase
            .table("salon_memberships")
            .select("id, status, last_event_type, next_charge_at, last_charged_at")
            .eq("salon_id", salon_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        membership = membership_resp.data if membership_resp else None
        if membership:
            membership_status = membership.get("status")

    session_status = str(session.get("status") or "PENDING").upper()
    subscription_status = str(subscription.get("status") if subscription else session_status).upper()
    seller_id = subscription.get("seller_id") if subscription else session.get("seller_id")
    seller_username = subscription.get("seller_username") if subscription else session.get("seller_username")

    success_statuses = {"ACTIVE", "COMPLETED", "RECURRENT_PAYMENT.ACTIVE", "RECURRENT_PAYMENT.COMPLETE"}
    is_completed = (
        subscription_status in success_statuses
        or session_status in success_statuses
        or (membership_status and membership_status.upper() == "ACTIVE")
    )

    if is_completed and not notification_sent:
        amount_jpy: Optional[int] = None
        billing_method = session_metadata.get("billing_method") or subscription_metadata.get("billing_method")
        if isinstance(billing_method, str) and billing_method.lower() in {"salon_yen", "yen"}:
            raw_amount = session_metadata.get("price_jpy") or subscription_metadata.get("price_jpy")
            if raw_amount is not None:
                try:
                    amount_jpy = int(raw_amount)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    amount_jpy = None

        points_value: Optional[int] = None
        if amount_jpy is None and plan:
            points_value = plan.points

        try:
            notification_id = send_purchase_notification(
                supabase,
                buyer_id=user_id,
                content_title=(salon_info or {}).get("title") or (plan.label if plan else "サブスクリプション"),
                content_type="オンラインサロン",
                seller_id=(salon_info or {}).get("owner_id") or seller_id,
                amount_jpy=amount_jpy,
                points=points_value,
            )
            if notification_id:
                session_metadata["purchase_notification_sent"] = True
                session_metadata["purchase_notification_id"] = notification_id
                supabase.table("one_lat_subscription_sessions").update({"metadata": session_metadata}).eq("id", session["id"]).execute()
                notification_sent = True
                if subscription:
                    subscription_metadata["purchase_notification_sent"] = True
                    subscription_metadata["purchase_notification_id"] = notification_id
                    supabase.table("user_subscriptions").update({"metadata": subscription_metadata}).eq("id", subscription["id"]).execute()

            seller_payment_method: Optional[str] = None
            if amount_jpy and points_value:
                seller_payment_method = "円 + ポイント決済"
            elif amount_jpy:
                seller_payment_method = "円決済"
            elif points_value:
                seller_payment_method = "ポイント決済"

            send_seller_purchase_notification(
                supabase,
                seller_id=(salon_info or {}).get("owner_id") or seller_id,
                content_title=(salon_info or {}).get("title") or (plan.label if plan else "サブスクリプション"),
                content_type="オンラインサロン",
                buyer_id=user_id,
                amount_jpy=amount_jpy,
                points=points_value,
                quantity=1,
                payment_method=seller_payment_method,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to deliver subscription notification",
                extra={
                    "external_id": external_id,
                    "user_id": user_id,
                    "error": str(exc),
                },
            )

    response_payload: Dict[str, Any] = {
        "external_id": external_id,
        "session_status": session_status,
        "subscription_status": subscription_status,
        "notification_sent": notification_sent,
        "is_completed": is_completed,
        "last_event_type": subscription.get("last_event_type") if subscription else session.get("last_event_type"),
        "last_event_at": subscription.get("last_event_at") if subscription else session.get("last_event_at"),
        "recurrent_payment_id": subscription.get("recurrent_payment_id") if subscription else None,
    }

    if plan:
        response_payload["plan"] = {
            "key": plan.key,
            "label": plan.label,
            "points": plan.points,
            "usd_amount": plan.usd_amount,
        }

    if seller_id or seller_username:
        response_payload["seller"] = {
            "id": seller_id,
            "username": seller_username,
        }

    if salon_info:
        response_payload["salon"] = {
            "id": salon_info.get("id"),
            "title": salon_info.get("title"),
        }
        response_payload["membership_status"] = membership_status.upper() if membership_status else None

    return response_payload



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
        salon_plan_id = salon_record.get("subscription_plan_id")
        # subscription_plan_idがplan_keyで保存されている場合も対応
        if salon_plan_id != plan.subscription_plan_id and salon_plan_id != plan.key:
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
