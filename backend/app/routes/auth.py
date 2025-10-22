import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from supabase import create_client, Client

from app.config import settings
from app.models.user import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    AuthResponse,
    ProfileUpdateRequest,
    GoogleAuthRequest
)
from app.utils.auth import create_access_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)


def generate_unique_username(supabase: Client, base_name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "", base_name) or "user"
    candidate = sanitized[:20] or "user"
    suffix = 1

    while True:
        existing = supabase.table("users").select("id").eq("username", candidate).limit(1).execute()
        if not existing.data:
            return candidate
        trimmed = sanitized[: max(1, 20 - len(str(suffix)))]
        candidate = f"{trimmed}{suffix}"
        suffix += 1


def build_user_response(user_info: dict) -> UserResponse:
    created_at = user_info.get("created_at") or user_info.get("updated_at") or datetime.utcnow().isoformat()
    return UserResponse(
        id=user_info["id"],
        email=user_info["email"],
        username=user_info["username"],
        user_type=user_info.get("user_type", "seller"),
        point_balance=user_info.get("point_balance", 0),
        created_at=created_at
    )

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
        
        user = build_user_response(user_info)
        return AuthResponse(
            user=user,
            access_token=create_access_token(user.id),
            refresh_token=""
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
        
        user = build_user_response(user_info)
        return AuthResponse(
            user=user,
            access_token=create_access_token(user.id),
            refresh_token=""
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ログインエラー: {str(e)}"
        )


@router.post("/google", response_model=AuthResponse)
async def login_with_google(payload: GoogleAuthRequest):
    """Google OAuth credentialでログイン/登録"""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuthの設定が完了していません"
        )

    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            settings.google_client_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google認証に失敗しました"
        ) from exc

    email = id_info.get("email")
    email_verified = id_info.get("email_verified", False)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Googleアカウントのメールアドレスを取得できませんでした"
        )

    if not email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="メールアドレスが確認済みのGoogleアカウントを利用してください"
        )

    supabase = get_supabase()

    user_response = supabase.table("users").select("*").eq("email", email).limit(1).execute()

    if user_response.data:
        user_info = user_response.data[0]
    else:
        display_name = id_info.get("name") or email.split("@")[0]
        username = generate_unique_username(supabase, display_name)
        new_user = {
            "id": str(uuid4()),
            "email": email,
            "username": username,
            "user_type": "seller",
            "point_balance": 0,
            "created_at": datetime.utcnow().isoformat(),
        }

        created = supabase.table("users").insert(new_user).execute()
        if not created.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ユーザー情報の作成に失敗しました"
            )
        user_info = created.data[0]

    user = build_user_response(user_info)
    access_token = create_access_token(user.id)

    return AuthResponse(
        user=user,
        access_token=access_token,
        refresh_token=""
    )

@router.get("/me", response_model=UserResponse)
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    現在のユーザー情報取得
    
    Authorizationヘッダーに Bearer トークンを指定してください
    """
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
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
        return build_user_response(user_info)
        
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
        # 署名付きトークンのクライアント側破棄で完了
        return {"message": "ログアウトしました"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ログアウトエラー: {str(e)}"
        )

@router.put("/profile", response_model=UserResponse)
async def update_profile(
    data: ProfileUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    プロフィール更新
    
    - **username**: 新しいユーザー名（3-20文字、英数字とアンダースコアのみ）
    
    Authorizationヘッダーに Bearer トークンを指定してください
    """
    try:
        token = credentials.credentials
        supabase = get_supabase()

        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        
        # 現在のユーザー情報を取得
        user_response = supabase.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません"
            )
        
        update_data = {}
        
        # ユーザー名の更新
        if data.username:
            # ユーザー名の重複チェック
            existing_user = supabase.table("users").select("id").eq("username", data.username).execute()
            
            if existing_user.data and existing_user.data[0]["id"] != user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="このユーザー名は既に使用されています"
                )
            
            update_data["username"] = data.username
        
        # 更新がある場合のみ実行
        if update_data:
            updated_user = supabase.table("users").update(update_data).eq("id", user_id).execute()
            
            if not updated_user.data:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="プロフィールの更新に失敗しました"
                )
            
            return build_user_response(updated_user.data[0])
        else:
            # 更新がない場合は現在の情報を返す
            return build_user_response(user_response.data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"プロフィール更新エラー: {str(e)}"
        )
