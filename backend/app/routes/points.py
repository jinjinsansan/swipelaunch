from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from app.models.points import (
    PointPurchaseRequest,
    PointPurchaseResponse,
    PointBalanceResponse,
    TransactionResponse,
    TransactionListResponse
)
from typing import Optional
from datetime import datetime

from app.utils.auth import decode_access_token
from app.services.one_lat import one_lat_client
import uuid

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
            "title": f"Point Purchase - {data.amount} points"
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
