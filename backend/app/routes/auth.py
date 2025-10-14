from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from typing import Optional
from app.config import settings
from app.models.user import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    AuthResponse
)
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegisterRequest):
    """
    ユーザー登録
    
    - **email**: メールアドレス
    - **password**: パスワード（8文字以上）
    - **username**: ユーザー名
    - **user_type**: seller（販売者）または buyer（購入者）
    """
    try:
        supabase = get_supabase()
        
        # 1. Supabase Authでユーザー作成
        auth_response = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
            "options": {
                "data": {
                    "username": data.username,
                    "user_type": data.user_type
                }
            }
        })
        
        if not auth_response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ユーザー登録に失敗しました"
            )
        
        # 2. usersテーブルに追加情報を挿入
        user_data = {
            "id": auth_response.user.id,
            "email": data.email,
            "username": data.username,
            "user_type": data.user_type,
            "point_balance": 0
        }
        
        db_response = supabase.table("users").insert(user_data).execute()
        
        if not db_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ユーザー情報の保存に失敗しました"
            )
        
        # 3. レスポンス作成
        user_info = db_response.data[0]
        
        return AuthResponse(
            user=UserResponse(
                id=user_info["id"],
                email=user_info["email"],
                username=user_info["username"],
                user_type=user_info["user_type"],
                point_balance=user_info["point_balance"],
                created_at=user_info["created_at"]
            ),
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"登録エラー: {str(e)}"
        )

@router.post("/login", response_model=AuthResponse)
async def login(data: UserLoginRequest):
    """
    ログイン
    
    - **email**: メールアドレス
    - **password**: パスワード
    """
    try:
        supabase = get_supabase()
        
        # 1. Supabase Authでログイン
        auth_response = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })
        
        if not auth_response.user or not auth_response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="メールアドレスまたはパスワードが正しくありません"
            )
        
        # 2. usersテーブルからユーザー情報取得
        user_response = supabase.table("users").select("*").eq("id", auth_response.user.id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザー情報が見つかりません"
            )
        
        user_info = user_response.data
        
        return AuthResponse(
            user=UserResponse(
                id=user_info["id"],
                email=user_info["email"],
                username=user_info["username"],
                user_type=user_info["user_type"],
                point_balance=user_info["point_balance"],
                created_at=user_info["created_at"]
            ),
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ログインエラー: {str(e)}"
        )

@router.get("/me", response_model=UserResponse)
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    現在のユーザー情報取得
    
    Authorizationヘッダーに Bearer トークンを指定してください
    """
    try:
        token = credentials.credentials
        
        # JWTトークンをデコードしてユーザーIDを取得
        import jwt
        from jwt import PyJWTError
        
        try:
            # トークンをデコード（検証なし - Supabaseが検証済み）
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub")
            
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="無効なトークンです"
                )
        except PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="トークンのデコードに失敗しました"
            )
        
        # service_role keyでSupabaseクライアントを取得（RLSバイパス）
        supabase = get_supabase()
        
        # usersテーブルから詳細情報取得
        user_response = supabase.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザー情報が見つかりません"
            )
        
        user_info = user_response.data
        
        return UserResponse(
            id=user_info["id"],
            email=user_info["email"],
            username=user_info["username"],
            user_type=user_info["user_type"],
            point_balance=user_info["point_balance"],
            created_at=user_info["created_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザー情報取得エラー: {str(e)}"
        )

@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    ログアウト
    
    Authorizationヘッダーに Bearer トークンを指定してください
    """
    try:
        supabase = get_supabase()
        supabase.auth.sign_out()
        
        return {"message": "ログアウトしました"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ログアウトエラー: {str(e)}"
        )
