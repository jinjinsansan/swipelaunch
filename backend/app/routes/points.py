from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from app.models.points import (
    PointPurchaseRequest,
    PointPurchaseResponse,
    PointBalanceResponse,
    TransactionResponse,
    TransactionListResponse,
    JPYCPurchaseRequest,
    JPYCPurchaseResponse,
    JPYCTransactionStatus
)
from typing import Optional
from datetime import datetime

from app.utils.auth import decode_access_token
from app.services.one_lat import one_lat_client
from app.services.jpyc_service import JPYCService, jpyc_to_wei
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/points", tags=["points"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """トークンから現在のユーザーIDを取得"""
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました"
        )

@router.post("/purchase/one-lat")
async def purchase_points_one_lat(
    data: PointPurchaseRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    ONE.latでポイント購入（USDT決済）
    
    - **amount**: 購入するポイント数（最低100ポイント）
    
    Returns:
        checkout_url: ONE.latの決済ページURL
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # ユーザー情報取得
        user_response = supabase.table("users").select("email, username").eq("id", user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません"
            )
        
        user = user_response.data
        
        # 金額計算（1 USD = 145円（ポイント））
        amount_usd = data.amount / 145.0
        
        # 一意のExternal ID生成
        external_id = f"point_purchase_{user_id}_{uuid.uuid4().hex[:8]}"
        
        # Webhook URL（本番環境では実際のURLに変更）
        # TODO: 本番環境では環境変数から取得
        backend_url = "https://swipelaunch-backend.onrender.com"
        frontend_url = "https://d-swipe.com"
        webhook_url = f"{backend_url}/api/webhooks/one-lat"
        success_url = f"{frontend_url}/points/purchase/success"
        error_url = f"{frontend_url}/points/purchase/error"
        
        # Checkout Preference作成
        checkout_data = await one_lat_client.create_checkout_preference(
            amount=amount_usd,
            currency="USD",
            title=f"Point Purchase - {data.amount} points",
            external_id=external_id,
            webhook_url=webhook_url,
            success_url=success_url,
            error_url=error_url,
            payer_email=user["email"],
            payer_name=user["username"]
        )
        
        # トランザクション記録（PENDING状態で保存）
        transaction_data = {
            "user_id": user_id,
            "checkout_preference_id": checkout_data.get("id"),
            "external_id": external_id,
            "amount": amount_usd,
            "currency": "USD",
            "status": "PENDING",
            "title": f"Point Purchase - {data.amount} points",
            "points_amount": data.amount  # ポイント数を保存
        }
        
        supabase.table("one_lat_transactions").insert(transaction_data).execute()
        
        return {
            "checkout_url": checkout_data.get("checkout_url"),
            "checkout_preference_id": checkout_data.get("id"),
            "external_id": external_id,
            "amount_usd": amount_usd,
            "points": data.amount
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ONE.lat決済エラー: {str(e)}"
        )


@router.post("/purchase/jpyc", response_model=JPYCPurchaseResponse)
async def purchase_points_jpyc(
    data: JPYCPurchaseRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    JPYC決済でポイント購入
    
    ガスレス決済（EIP-3009 transferWithAuthorization）
    
    Args:
        data: JPYC購入リクエスト（署名データ含む）
        credentials: 認証情報
        
    Returns:
        JPYCPurchaseResponse: 決済情報
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        logger.info(f"🔷 JPYC purchase request from user {user_id}")
        logger.info(f"   Points: {data.points_amount}, Chain: {data.chain_id}")
        
        # JPYCサービス初期化
        try:
            jpyc_service = JPYCService(chain_id=data.chain_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"サポートされていないブロックチェーンです: {str(e)}"
            )
        
        # JPYC金額（1ポイント = 1 JPYC）
        jpyc_amount = data.points_amount
        jpyc_amount_wei = jpyc_to_wei(jpyc_amount)
        
        # プラットフォームのアドレス取得
        to_address = jpyc_service.PLATFORM_ADDRESS
        
        # 署名検証
        logger.info(f"🔐 Verifying signature...")
        is_valid = jpyc_service.verify_signature(
            from_address=data.from_address,
            to_address=to_address,
            value=jpyc_amount_wei,
            valid_after=data.valid_after,
            valid_before=data.valid_before,
            nonce=data.nonce,
            signature_v=data.signature_v,
            signature_r=data.signature_r,
            signature_s=data.signature_s,
        )
        
        if not is_valid:
            logger.error(f"❌ Invalid signature")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="署名が無効です"
            )
        
        logger.info(f"✅ Signature verified")
        
        # トランザクション記録作成
        transaction_id = str(uuid.uuid4())
        transaction_data = {
            "id": transaction_id,
            "user_id": user_id,
            "from_address": data.from_address,
            "to_address": to_address,
            "amount": jpyc_amount,
            "points_amount": data.points_amount,
            "chain_id": data.chain_id,
            "status": "pending",
            "nonce": data.nonce,
            "signature_v": data.signature_v,
            "signature_r": data.signature_r,
            "signature_s": data.signature_s,
            "valid_after": data.valid_after,
            "valid_before": data.valid_before,
        }
        
        supabase.table("jpyc_transactions").insert(transaction_data).execute()
        logger.info(f"📝 Transaction record created: {transaction_id}")
        
        # TODO: トランザクション実行（リレイヤーの秘密鍵が設定されたら）
        # tx_hash = jpyc_service.execute_transfer_with_authorization(...)
        # if tx_hash:
        #     supabase.table("jpyc_transactions").update({
        #         "status": "submitted",
        #         "tx_hash": tx_hash
        #     }).eq("id", transaction_id).execute()
        
        logger.warning(f"⚠️ Transaction execution is not implemented yet")
        logger.warning(f"⚠️ Manual processing required for transaction: {transaction_id}")
        
        # レスポンス
        return JPYCPurchaseResponse(
            transaction_id=transaction_id,
            status="pending",
            points_amount=data.points_amount,
            jpyc_amount=jpyc_amount,
            from_address=data.from_address,
            to_address=to_address,
            chain_id=data.chain_id,
            estimated_confirmation_time=30,  # Polygon: 約30秒
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ JPYC purchase error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"JPYC決済エラー: {str(e)}"
        )


@router.get("/purchase/jpyc/{transaction_id}", response_model=JPYCTransactionStatus)
async def get_jpyc_transaction_status(
    transaction_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    JPYC決済のステータス確認
    
    Args:
        transaction_id: トランザクションID
        credentials: 認証情報
        
    Returns:
        JPYCTransactionStatus: トランザクションステータス
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # トランザクション取得
        response = supabase.table("jpyc_transactions").select("*").eq("id", transaction_id).eq("user_id", user_id).single().execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="トランザクションが見つかりません"
            )
        
        tx = response.data
        
        return JPYCTransactionStatus(
            transaction_id=tx["id"],
            status=tx["status"],
            tx_hash=tx.get("tx_hash"),
            block_number=tx.get("block_number"),
            points_amount=tx["points_amount"],
            jpyc_amount=tx["amount"],
            created_at=tx["created_at"],
            confirmed_at=tx.get("confirmed_at"),
            completed_at=tx.get("completed_at"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステータス取得エラー: {str(e)}"
        )


@router.post("/purchase", response_model=PointPurchaseResponse, status_code=status.HTTP_201_CREATED)
async def purchase_points(
    data: PointPurchaseRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    ポイント購入
    
    - **amount**: 購入するポイント数（最低100ポイント）
    
    Note: 本番環境では決済処理（Stripe等）を実装してください
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # ユーザー情報取得
        user_response = supabase.table("users").select("point_balance").eq("id", user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません"
            )
        
        current_balance = user_response.data.get("point_balance", 0)
        new_balance = current_balance + data.amount
        
        # ポイント残高を更新
        supabase.table("users").update({"point_balance": new_balance}).eq("id", user_id).execute()
        
        # トランザクション記録
        transaction_data = {
            "user_id": user_id,
            "transaction_type": "purchase",
            "amount": data.amount,
            "description": f"{data.amount}ポイントを購入しました"
        }
        
        transaction_response = supabase.table("point_transactions").insert(transaction_data).execute()
        
        if not transaction_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="トランザクション記録に失敗しました"
            )
        
        transaction = transaction_response.data[0]
        
        return PointPurchaseResponse(
            transaction_id=transaction["id"],
            amount=data.amount,
            new_balance=new_balance,
            purchased_at=transaction["created_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ポイント購入エラー: {str(e)}"
        )

@router.get("/balance", response_model=PointBalanceResponse)
async def get_point_balance(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    ポイント残高取得
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # ユーザー情報取得
        user_response = supabase.table("users").select("username, point_balance, updated_at").eq("id", user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません"
            )
        
        user = user_response.data
        
        return PointBalanceResponse(
            user_id=user_id,
            username=user["username"],
            point_balance=user.get("point_balance", 0),
            last_updated=user["updated_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ポイント残高取得エラー: {str(e)}"
        )

@router.get("/transactions", response_model=TransactionListResponse)
async def get_transactions(
    transaction_type: Optional[str] = Query(None, description="トランザクションタイプでフィルター（purchase, product_purchase, refund）"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    トランザクション履歴取得
    
    - **transaction_type**: トランザクションタイプでフィルター
    - **limit**: 取得件数
    - **offset**: オフセット
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # クエリ構築
        query = supabase.table("point_transactions").select("*").eq("user_id", user_id)
        
        if transaction_type:
            query = query.eq("transaction_type", transaction_type)
        
        # 件数取得
        count_response = query.execute()
        total = len(count_response.data) if count_response.data else 0
        
        # データ取得（ページネーション + 降順）
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        
        transactions = [TransactionResponse(**tx) for tx in response.data] if response.data else []
        
        return TransactionListResponse(
            data=transactions,
            total=total,
            limit=limit,
            offset=offset,
            transaction_type_filter=transaction_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"トランザクション履歴取得エラー: {str(e)}"
        )
