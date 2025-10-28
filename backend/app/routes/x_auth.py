"""
X (Twitter) OAuth 2.0 認証ルート
"""

import secrets
import hashlib
import base64
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client
from pydantic import BaseModel

from app.config import settings
from app.utils.auth import decode_access_token
from app.services.x_api import XOAuthClient, XAPIClient, XAPIError

router = APIRouter(prefix="/auth/x", tags=["x_auth"])
security = HTTPBearer()


def get_supabase() -> Client:
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_key)


def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """認証トークンからユーザーIDを取得"""
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効な認証トークンです"
        )
    return payload["sub"]


# PKCEチャレンジ生成（簡易版 - 実際にはセッションストアが必要）
# TODO: Redisなどでstate/code_verifierを管理
_pkce_store = {}  # 本番環境では Redis などを使用


def generate_pkce_pair() -> tuple[str, str]:
    """PKCE用のcode_verifierとcode_challengeを生成"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge


class XConnectionStatus(BaseModel):
    is_connected: bool
    x_username: Optional[str] = None
    x_user_id: Optional[str] = None
    connected_at: Optional[str] = None
    followers_count: Optional[int] = None


class XConnectionResponse(BaseModel):
    message: str
    x_username: str
    x_user_id: str
    followers_count: int


@router.get("/authorize")
async def x_authorize(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    X OAuth認証開始
    
    認証URLにリダイレクトし、ユーザーにX連携を承認させる
    """
    user_id = get_current_user_id(credentials)
    
    # OAuth クライアント初期化
    oauth_client = XOAuthClient(
        client_id=settings.x_api_client_id,
        client_secret=settings.x_api_client_secret,
        redirect_uri=settings.x_oauth_callback_url
    )
    
    # CSRF対策用のstateとPKCE生成
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()
    
    # stateとcode_verifierを一時保存（TODO: Redis使用）
    _pkce_store[state] = {
        "user_id": user_id,
        "code_verifier": code_verifier,
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }
    
    # 認証URLを生成
    auth_url = oauth_client.get_authorization_url(state, code_challenge)
    
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def x_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter")
):
    """
    X OAuth コールバック
    
    認証コードをアクセストークンに交換し、ユーザー情報を取得して保存
    """
    # state検証
    if state not in _pkce_store:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無効なstateパラメータです"
        )
    
    pkce_data = _pkce_store[state]
    
    # 有効期限チェック
    if datetime.utcnow() > pkce_data["expires_at"]:
        del _pkce_store[state]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="認証セッションの有効期限が切れました"
        )
    
    user_id = pkce_data["user_id"]
    code_verifier = pkce_data["code_verifier"]
    
    # OAuth クライアント初期化
    oauth_client = XOAuthClient(
        client_id=settings.x_api_client_id,
        client_secret=settings.x_api_client_secret,
        redirect_uri=settings.x_oauth_callback_url
    )
    
    try:
        # 認証コードをトークンに交換
        token_data = await oauth_client.exchange_code_for_token(code, code_verifier)
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 7200)  # デフォルト2時間
        
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="アクセストークンの取得に失敗しました"
            )
        
        # X API クライアントでユーザー情報取得
        x_client = XAPIClient(access_token)
        user_info = await x_client.get_user_info()
        
        # user_x_connectionsテーブルに保存
        supabase = get_supabase()
        
        connection_data = {
            "user_id": user_id,
            "x_user_id": user_info["x_user_id"],
            "x_username": user_info["x_username"],
            "access_token": access_token,  # TODO: 暗号化
            "refresh_token": refresh_token,  # TODO: 暗号化
            "token_expires_at": (
                datetime.utcnow() + timedelta(seconds=expires_in)
            ).isoformat(),
            "account_created_at": user_info.get("account_created_at"),
            "followers_count": user_info.get("followers_count", 0),
            "is_verified": user_info.get("is_verified", False)
        }
        
        # UPSERT（既存の場合は更新）
        supabase.table("user_x_connections").upsert(
            connection_data,
            on_conflict="user_id"
        ).execute()
        
        # stateを削除
        del _pkce_store[state]
        
        # フロントエンドにリダイレクト（成功）
        frontend_url = settings.frontend_url or "https://d-swipe.com"
        return RedirectResponse(
            url=f"{frontend_url}/settings?x_connected=true"
        )
    
    except XAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"X連携に失敗しました: {str(e)}"
        )


@router.get("/status", response_model=XConnectionStatus)
async def get_x_connection_status(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    X連携状態確認
    """
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    
    try:
        response = supabase.table("user_x_connections").select(
            "x_user_id, x_username, connected_at, followers_count"
        ).eq(
            "user_id", user_id
        ).maybe_single().execute()
        
        if response.data:
            return XConnectionStatus(
                is_connected=True,
                x_username=response.data.get("x_username"),
                x_user_id=response.data.get("x_user_id"),
                connected_at=response.data.get("connected_at"),
                followers_count=response.data.get("followers_count")
            )
        else:
            return XConnectionStatus(is_connected=False)
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"連携状態の確認に失敗しました: {str(e)}"
        )


@router.delete("/disconnect")
async def disconnect_x(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    X連携解除
    """
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    
    try:
        supabase.table("user_x_connections").delete().eq(
            "user_id", user_id
        ).execute()
        
        return {"message": "X連携を解除しました"}
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"連携解除に失敗しました: {str(e)}"
        )
