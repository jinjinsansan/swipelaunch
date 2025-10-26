"""
Webhook endpoints for payment notifications
"""
from fastapi import APIRouter, Request, HTTPException
from app.services.one_lat import one_lat_client
from app.config import get_supabase_client
import logging

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


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
        
        if entity_type != "PAYMENT_ORDER":
            logger.warning(f"⚠️ Unsupported entity_type: {entity_type}")
            return {"status": "ignored"}
        
        # Payment Order詳細を取得
        payment_order = await one_lat_client.get_payment_order(entity_id)
        
        # データベースから対応するトランザクションを検索
        supabase = get_supabase_client()
        
        # Payment Order IDで検索
        response = supabase.table("one_lat_transactions").select("*").eq("payment_order_id", entity_id).execute()
        
        if not response.data:
            # External IDで検索（Payment Order作成前の場合）
            external_id = payment_order.get("external_id")
            if external_id:
                response = supabase.table("one_lat_transactions").select("*").eq("external_id", external_id).execute()
        
        if not response.data:
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
        
        # ポイント購入の場合（titleに"Point Purchase"が含まれる）
        if "Point" in transaction.get("title", ""):
            # ユーザーのポイント残高を更新
            # 為替レート: 1 USD = 100 ポイント（仮）
            points_to_add = int(amount * 100)
            
            # ユーザー情報取得
            user_response = supabase.table("users").select("points").eq("id", user_id).execute()
            
            if user_response.data:
                current_points = user_response.data[0].get("points", 0)
                new_points = current_points + points_to_add
                
                # ポイント更新
                supabase.table("users").update({"points": new_points}).eq("id", user_id).execute()
                
                logger.info(f"✅ Points added to user {user_id}: +{points_to_add} (Total: {new_points})")
            
        # LP購入の場合（別途処理）
        # TODO: LP購入処理を実装
        
        logger.info(f"✅ Payment success handled for transaction: {transaction['id']}")
        
    except Exception as e:
        logger.error(f"❌ Failed to handle payment success: {str(e)}")
        raise
