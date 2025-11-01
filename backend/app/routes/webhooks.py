"""
Webhook endpoints for payment notifications
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException

from app.config import get_supabase_client
from app.constants.subscription_plans import (
    get_subscription_plan,
    get_subscription_plan_by_id,
)
from app.services.one_lat import one_lat_client
from supabase import Client
import logging

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


STATUS_MAP = {
    "OPENED": "PENDING",
    "CREATED": "PENDING",
    "PENDING": "PENDING",
    "CLOSED": "COMPLETED",
    "EXPIRED": "EXPIRED",
    "REJECTED": "REJECTED",
    "REFUNDED": "REFUNDED",
    "CANCELLED": "CANCELLED",
}


def _map_payment_status(raw_status: Optional[str]) -> str:
    status_value = (raw_status or "").upper()
    return STATUS_MAP.get(status_value, "PENDING")


def _ensure_metadata_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:  # pragma: no cover - defensive
            return {}
    return {}


def _fulfill_product_order(supabase: Client, order_row: Dict[str, Any]) -> None:
    product_id = order_row.get("item_id")
    if not product_id:
        return

    quantity = int((order_row.get("metadata") or {}).get("quantity") or 1)
    try:
        product_resp = (
            supabase
            .table("products")
            .select("id, stock_quantity, total_sales")
            .eq("id", product_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load product for payment order", extra={"error": str(exc), "product_id": product_id})
        return

    product = product_resp.data if product_resp else None
    if not product:
        logger.warning("Product not found for payment order", extra={"product_id": product_id})
        return

    updates: Dict[str, Any] = {}
    stock_quantity = product.get("stock_quantity")
    if stock_quantity is not None:
        try:
            new_stock = max(int(stock_quantity) - quantity, 0)
            updates["stock_quantity"] = new_stock
        except (TypeError, ValueError):  # pragma: no cover - defensive
            logger.warning("Invalid stock quantity when fulfilling order", extra={"product_id": product_id})

    try:
        current_sales = int(product.get("total_sales") or 0)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        current_sales = 0
    updates["total_sales"] = current_sales + quantity

    try:
        supabase.table("products").update(updates).eq("id", product_id).execute()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to update product after payment", extra={"error": str(exc), "product_id": product_id})


def _fulfill_note_order(supabase: Client, order_row: Dict[str, Any]) -> None:
    note_id = order_row.get("item_id")
    user_id = order_row.get("user_id")
    if not note_id or not user_id:
        return

    payload = {
        "note_id": note_id,
        "buyer_id": user_id,
        "points_spent": 0,
        "purchased_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase.table("note_purchases").insert(payload).execute()
    except Exception as exc:
        if "duplicate key" in str(exc).lower():
            logger.info("Note purchase already recorded", extra={"note_id": note_id, "user_id": user_id})
        else:  # pragma: no cover - defensive
            logger.error("Failed to record note purchase", extra={"error": str(exc), "note_id": note_id, "user_id": user_id})


def _fulfill_payment_order(supabase: Client, order_row: Dict[str, Any]) -> None:
    item_type = order_row.get("item_type")
    if item_type == "product":
        _fulfill_product_order(supabase, order_row)
    elif item_type == "note":
        _fulfill_note_order(supabase, order_row)
    elif item_type == "salon":
        logger.info("Salon payment fulfillment is not implemented yet", extra={"order_id": order_row.get("id")})


async def _process_payment_order(
    supabase: Client,
    payment_order_payload: Dict[str, Any],
    event_type: Optional[str]
) -> bool:
    entity_id = payment_order_payload.get("id") or payment_order_payload.get("payment_order_id")
    external_id = payment_order_payload.get("external_id")

    order_resp = None
    if entity_id:
        order_resp = (
            supabase
            .table("payment_orders")
            .select("*")
            .eq("payment_order_id", entity_id)
            .maybe_single()
            .execute()
        )

    if (not order_resp or not order_resp.data) and external_id:
        order_resp = (
            supabase
            .table("payment_orders")
            .select("*")
            .eq("external_id", external_id)
            .maybe_single()
            .execute()
        )

    if not order_resp or not order_resp.data:
        return False

    order_row = order_resp.data
    previous_status = str(order_row.get("status") or "").upper()
    new_status = _map_payment_status(payment_order_payload.get("status"))

    metadata = _ensure_metadata_dict(order_row.get("metadata"))
    metadata.update({
        "one_lat_status": payment_order_payload.get("status"),
        "last_event_type": event_type,
        "payment_order_id": entity_id,
    })

    now_iso = datetime.now(timezone.utc).isoformat()
    update_payload: Dict[str, Any] = {
        "payment_order_id": entity_id,
        "status": new_status,
        "metadata": metadata,
    }

    if new_status == "COMPLETED" and previous_status != "COMPLETED":
        metadata["fulfilled_at"] = now_iso
        update_payload["completed_at"] = now_iso
    elif new_status in {"CANCELLED", "EXPIRED", "REJECTED", "REFUNDED"}:
        update_payload["canceled_at"] = now_iso

    try:
        supabase.table("payment_orders").update(update_payload).eq("id", order_row["id"]).execute()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to update payment order", extra={"error": str(exc), "order_id": order_row.get("id")})
        return True

    if new_status == "COMPLETED" and previous_status != "COMPLETED":
        merged_row = dict(order_row)
        merged_row.update(update_payload)
        merged_row["metadata"] = metadata
        _fulfill_payment_order(supabase, merged_row)

    return True


@router.post("/one-lat")
async def one_lat_webhook(request: Request):
    """
    ONE.latからのWebhook通知を受信
    
    通知形式:
    {
      "id": "uCEarm1kXJsroMQ6dt",
      "event_type": "PAYMENT_ORDER.CLOSED",
      "entity_type": "PAYMENT_ORDER",
      "entity_id": "rcAaNfKdKJRmrnj4l5"
    }
    
    event_type:
    - PAYMENT_ORDER.OPENED: 決済開始
    - PAYMENT_ORDER.CLOSED: 決済完了
    - PAYMENT_ORDER.EXPIRED: 期限切れ
    - PAYMENT_ORDER.REJECTED: 拒否
    - PAYMENT_ORDER.REFUNDED: 返金
    """
    try:
        # Webhookペイロード取得
        payload = await request.json()
        logger.info(f"📩 ONE.lat Webhook received: {payload}")
        
        event_type = payload.get("event_type")
        entity_type = payload.get("entity_type")
        entity_id = payload.get("entity_id")
        webhook_id = payload.get("id")
        
        if entity_type == "PAYMENT_ORDER":
            # Payment Order詳細を取得
            payment_order = await one_lat_client.get_payment_order(entity_id)

            # データベースから対応するトランザクションを検索
            supabase = get_supabase_client()
            order_handled = await _process_payment_order(supabase, payment_order, event_type)

            # Payment Order IDで検索
            response = (
                supabase.table("one_lat_transactions").select("*").eq("payment_order_id", entity_id).execute()
            )

            if not response.data:
                if order_handled:
                    logger.info("✅ Payment order handled via payment_orders", extra={"payment_order_id": entity_id})
                    return {"status": "success"}
                # External IDで検索（Payment Order作成前の場合）
                external_id = payment_order.get("external_id")
                if external_id:
                    response = (
                        supabase.table("one_lat_transactions").select("*").eq("external_id", external_id).execute()
                    )

            if not response.data:
                if order_handled:
                    logger.info("✅ Payment order already processed", extra={"payment_order_id": entity_id})
                    return {"status": "success"}
                logger.error(f"❌ Transaction not found for payment_order_id: {entity_id}")
                return {"status": "error", "message": "Transaction not found"}

            transaction = response.data[0]

            # トランザクション情報を更新
            update_data = {
                "payment_order_id": entity_id,
                "status": payment_order.get("status"),
                "payment_method_type": payment_order.get("payment_method_type"),
                "webhook_notification_id": webhook_id
            }

            # Payerの情報を更新
            if payment_order.get("payer"):
                payer = payment_order["payer"]
                update_data["payer_email"] = payer.get("email")
                update_data["payer_name"] = f"{payer.get('first_name', '')} {payer.get('last_name', '')}".strip()

            supabase.table("one_lat_transactions").update(update_data).eq("id", transaction["id"]).execute()

            logger.info(f"✅ Transaction updated: {transaction['id']} - Status: {update_data['status']}")

            # 決済完了時の処理
            if event_type == "PAYMENT_ORDER.CLOSED" and payment_order.get("status") == "CLOSED":
                await handle_payment_success(transaction, payment_order)

            return {"status": "success"}

        if entity_type == "RECURRENT_PAYMENT":
            recurrent_payment = await one_lat_client.get_recurrent_payment(entity_id)
            await handle_recurrent_payment_event(payload, recurrent_payment)
            return {"status": "success"}

        logger.warning(f"⚠️ Unsupported entity_type: {entity_type}")
        return {"status": "ignored"}
        
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_payment_success(transaction: dict, payment_order: dict):
    """
    決済完了時の処理
    
    Args:
        transaction: データベースのトランザクション情報
        payment_order: ONE.latのPayment Order情報
    """
    try:
        supabase = get_supabase_client()
        user_id = transaction["user_id"]
        amount = float(payment_order.get("amount", 0))
        
        # ポイント購入の場合（titleに"Point"が含まれる）
        title = transaction.get("title", "")
        logger.info(f"🔍 Transaction title: '{title}'")
        
        if "Point" in title or "point" in title:
            # トランザクションに保存されたポイント数を使用（正確な付与のため）
            points_to_add = transaction.get("points_amount")
            
            if not points_to_add:
                # フォールバック: USD金額から計算（為替レート: 1 USD = 145円）
                points_to_add = int(amount * 145)
                logger.warning(f"⚠️ points_amount not found, calculated from amount: {points_to_add}")
            
            logger.info(f"💰 Attempting to add {points_to_add} points to user {user_id}")
            
            # ユーザー情報取得
            user_response = supabase.table("users").select("point_balance").eq("id", user_id).execute()
            logger.info(f"👤 User query result: {user_response.data}")
            
            if user_response.data:
                current_points = user_response.data[0].get("point_balance", 0)
                new_points = current_points + points_to_add
                
                # ポイント更新
                update_response = supabase.table("users").update({"point_balance": new_points}).eq("id", user_id).execute()
                logger.info(f"📝 Update response: {update_response.data}")
                
                # point_transactions テーブルにも記録（フロントエンドの履歴表示用）
                point_transaction_data = {
                    "user_id": user_id,
                    "transaction_type": "purchase",
                    "amount": points_to_add,
                    "description": f"Point Purchase via ONE.lat - {amount} USD"
                }
                supabase.table("point_transactions").insert(point_transaction_data).execute()
                logger.info(f"📋 Transaction record added to point_transactions")
                
                logger.info(f"✅ Points added to user {user_id}: +{points_to_add} (Total: {new_points})")
            else:
                logger.error(f"❌ User not found: {user_id}")
        else:
            logger.warning(f"⚠️ Transaction title '{title}' does not contain 'Point' - skipping point addition")
            
        # LP購入の場合（別途処理）
        # TODO: LP購入処理を実装
        
        logger.info(f"✅ Payment success handled for transaction: {transaction['id']}")
        
    except Exception as e:
        logger.error(f"❌ Failed to handle payment success: {str(e)}")
        raise


def _extract_datetime_value(data: Dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


async def handle_recurrent_payment_event(payload: Dict[str, Any], recurrent_payment: Dict[str, Any]):
    """Handle ONE.lat recurrent payment webhook events."""

    supabase = get_supabase_client()

    event_id = payload.get("id")
    event_type = str(payload.get("event_type", "")).upper()
    recurrent_payment_id = payload.get("entity_id")
    status = recurrent_payment.get("status")
    external_id = recurrent_payment.get("external_id")
    subscription_plan_id = (
        recurrent_payment.get("payment_link_id")
        or recurrent_payment.get("subscription_id")
    )

    session = None
    if external_id:
        session_response = (
            supabase.table("one_lat_subscription_sessions")
            .select("*")
            .eq("external_id", external_id)
            .single()
            .execute()
        )
        session = session_response.data if session_response.data else None

    if not session and recurrent_payment_id:
        session_response = (
            supabase.table("one_lat_subscription_sessions")
            .select("*")
            .eq("recurrent_payment_id", recurrent_payment_id)
            .single()
            .execute()
        )
        session = session_response.data if session_response.data else None

    plan = None
    if session:
        plan = get_subscription_plan(session.get("plan_key", ""))
    if not plan and subscription_plan_id:
        plan = get_subscription_plan_by_id(subscription_plan_id)

    if not plan:
        logger.error(
            "❌ Subscription plan not found",
            extra={
                "external_id": external_id,
                "recurrent_payment_id": recurrent_payment_id,
                "subscription_plan_id": subscription_plan_id,
            },
        )
        return

    # Resolve user id
    user_id: Optional[str] = session.get("user_id") if session else None
    payer_email: Optional[str] = None
    payer_info = recurrent_payment.get("payer") or recurrent_payment.get("customer")
    if isinstance(payer_info, dict):
        payer_email = (
            payer_info.get("email")
            or payer_info.get("payer_email")
            or payer_info.get("customer_email")
        )

    if not user_id and payer_email:
        user_lookup = (
            supabase.table("users").select("id").eq("email", payer_email).single().execute()
        )
        if user_lookup.data:
            user_id = user_lookup.data["id"]

    if not user_id:
        logger.error(
            "❌ Unable to resolve user for recurrent payment",
            extra={
                "external_id": external_id,
                "recurrent_payment_id": recurrent_payment_id,
                "payer_email": payer_email,
            },
        )
        return

    now = datetime.now(timezone.utc)

    session_metadata = _ensure_metadata_dict(session.get("metadata")) if session else {}
    billing_method = session_metadata.get("billing_method") if isinstance(session_metadata, dict) else None
    billing_method_normalized = str(billing_method).lower() if billing_method is not None else ""

    if not session:
        # Create a minimal session record to keep mappings consistent
        session_payload = {
            "user_id": user_id,
            "plan_key": plan.key,
            "subscription_plan_id": plan.subscription_plan_id,
            "points_per_cycle": plan.points,
            "usd_amount": plan.usd_amount,
            "external_id": external_id or f"auto_{recurrent_payment_id}",
            "recurrent_payment_id": recurrent_payment_id,
            "status": status or event_type,
            "metadata": session_metadata,
        }
        insert_response = (
            supabase.table("one_lat_subscription_sessions").insert(session_payload).execute()
        )
        session = insert_response.data[0] if insert_response.data else session_payload

    # Keep session in sync
    salon_id: Optional[str] = session.get("salon_id") if isinstance(session, dict) else None
    if not salon_id and isinstance(subscription, dict):
        salon_id = subscription.get("salon_id")
    if not salon_id:
        metadata = session.get("metadata") if isinstance(session, dict) else None
        if isinstance(metadata, dict):
            salon_id = metadata.get("salon_id") or metadata.get("salon")

    session_update = {
        "status": status or event_type,
        "recurrent_payment_id": recurrent_payment_id,
    }
    if salon_id:
        session_update["salon_id"] = salon_id
    if session_metadata:
        session_update["metadata"] = session_metadata
    supabase.table("one_lat_subscription_sessions").update(session_update).eq(
        "id", session.get("id")
    ).execute()

    # Upsert user subscription
    subscription_response = (
        supabase.table("user_subscriptions")
        .select("*")
        .eq("recurrent_payment_id", recurrent_payment_id)
        .single()
        .execute()
    )
    subscription = subscription_response.data if subscription_response.data else None

    next_charge_at = _extract_datetime_value(
        recurrent_payment,
        [
            "next_payment_at",
            "next_payment_date",
            "next_execution_date",
            "next_billing_date",
        ],
    )

    subscription_update = {
        "status": status or (subscription.get("status") if subscription else "ACTIVE"),
        "last_event_type": event_type,
        "last_event_at": now.isoformat(),
        "next_charge_at": next_charge_at,
        "seller_id": session.get("seller_id"),
        "seller_username": session.get("seller_username"),
        "metadata": session_metadata,
    }
    if salon_id:
        subscription_update["salon_id"] = salon_id

    if subscription:
        supabase.table("user_subscriptions").update(subscription_update).eq(
            "id", subscription["id"]
        ).execute()
    else:
        subscription_payload = {
            "user_id": user_id,
            "plan_key": plan.key,
            "subscription_plan_id": plan.subscription_plan_id,
            "points_per_cycle": plan.points,
            "usd_amount": plan.usd_amount,
            "checkout_preference_id": session.get("checkout_preference_id"),
            "external_id": session.get("external_id"),
            "recurrent_payment_id": recurrent_payment_id,
            "status": subscription_update["status"],
            "last_event_type": event_type,
            "last_event_at": now.isoformat(),
            "next_charge_at": next_charge_at,
            "seller_id": session.get("seller_id"),
            "seller_username": session.get("seller_username"),
            "metadata": session_metadata,
        }
        if salon_id:
            subscription_payload["salon_id"] = salon_id
        insert_subscription = (
            supabase.table("user_subscriptions").insert(subscription_payload).execute()
        )
        subscription = insert_subscription.data[0] if insert_subscription.data else subscription_payload

    subscription_id = subscription.get("id") if isinstance(subscription, dict) else None
    if not subscription_id:
        subscription_lookup = (
            supabase.table("user_subscriptions")
            .select("id")
            .eq("recurrent_payment_id", recurrent_payment_id)
            .single()
            .execute()
        )
        if subscription_lookup.data:
            subscription_id = subscription_lookup.data["id"]
            if isinstance(subscription, dict):
                subscription["id"] = subscription_id
        else:
            logger.error(
                "❌ Failed to resolve subscription id for recurrent payment",
                extra={"recurrent_payment_id": recurrent_payment_id},
            )
            return

    success_events = {"RECURRENT_PAYMENT.ACTIVE", "RECURRENT_PAYMENT.COMPLETE"}
    cancel_events = {"RECURRENT_PAYMENT.CANCELED", "RECURRENT_PAYMENT.CANCELLED"}
    unpaid_events = {"RECURRENT_PAYMENT.UNPAID", "RECURRENT_PAYMENT.PAUSED"}

    history_check = (
        supabase.table("subscription_charge_history")
        .select("id")
        .eq("event_id", event_id)
        .execute()
    )
    already_processed = bool(history_check.data)

    points_awarded = 0
    if event_type in success_events and not already_processed:
        if billing_method_normalized in {"salon_yen", "yen"}:
            subscription_update["last_charge_at"] = now.isoformat()
        else:
            user_response = (
                supabase.table("users").select("point_balance").eq("id", user_id).single().execute()
            )
            current_points = user_response.data.get("point_balance", 0) if user_response.data else 0
            new_balance = current_points + plan.points

            supabase.table("users").update({"point_balance": new_balance}).eq("id", user_id).execute()

            point_transaction = {
                "user_id": user_id,
                "transaction_type": "subscription_credit",
                "amount": plan.points,
                "description": f"Subscription auto recharge ({plan.label})",
            }
            supabase.table("point_transactions").insert(point_transaction).execute()

            points_awarded = plan.points
            subscription_update["last_charge_at"] = now.isoformat()

    if event_type in cancel_events:
        subscription_update["status"] = "CANCELED"
    elif status and str(status).upper() == "UNPAID":
        subscription_update["status"] = "UNPAID"

    if salon_id and subscription_id:
        membership_status = subscription_update["status"]
        if event_type in success_events:
            membership_status = "ACTIVE"
        elif event_type in cancel_events:
            membership_status = "CANCELED"
        elif event_type in unpaid_events or (status and str(status).upper() == "UNPAID"):
            membership_status = "UNPAID"

        membership_response = (
            supabase.table("salon_memberships")
            .select("id")
            .eq("salon_id", salon_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )

        membership_data = {
            "salon_id": salon_id,
            "user_id": user_id,
            "status": membership_status,
            "recurrent_payment_id": recurrent_payment_id,
            "subscription_session_external_id": session.get("external_id"),
            "last_event_type": event_type,
            "next_charge_at": next_charge_at,
        }

        if event_type in success_events:
            membership_data["last_charged_at"] = now.isoformat()
            if not membership_response.data:
                membership_data["joined_at"] = now.isoformat()
        if event_type in cancel_events:
            membership_data["canceled_at"] = now.isoformat()

        if membership_response.data:
            supabase.table("salon_memberships").update(membership_data).eq(
                "id", membership_response.data["id"]
            ).execute()
        else:
            supabase.table("salon_memberships").insert(membership_data).execute()

    supabase.table("user_subscriptions").update(subscription_update).eq(
        "id", subscription_id
    ).execute()

    amount_value = recurrent_payment.get("amount")
    if isinstance(amount_value, dict):
        amount_usd = amount_value.get("value") or amount_value.get("amount")
    else:
        amount_usd = amount_value
    if amount_usd is None:
        amount_usd = plan.usd_amount

    if not already_processed:
        history_payload = {
            "user_subscription_id": subscription_id,
            "event_id": event_id,
            "event_type": event_type,
            "status": status,
            "amount_usd": amount_usd,
            "points_granted": points_awarded,
            "raw_payload": {
                "webhook": payload,
                "recurrent_payment": recurrent_payment,
            },
        }
        if salon_id:
            history_payload["salon_id"] = salon_id
        supabase.table("subscription_charge_history").insert(history_payload).execute()

    logger.info(
        "✅ Recurrent payment processed",
        extra={
            "event_type": event_type,
            "recurrent_payment_id": recurrent_payment_id,
            "points_awarded": points_awarded,
            "status": subscription_update["status"],
        },
    )
