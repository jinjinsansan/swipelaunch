import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from supabase import create_client, Client
from typing import Optional

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

LAST_LOGIN_FIELD_AVAILABLE = True

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)


def update_last_login_timestamp(supabase: Client, user_id: str, context: str) -> Optional[str]:
    """Update last_login_at column if available, suppressing repeated schema warnings."""
    global LAST_LOGIN_FIELD_AVAILABLE
    if not LAST_LOGIN_FIELD_AVAILABLE:
        return None

    last_login_value = datetime.utcnow().isoformat()
    try:
        supabase.table("users").update({"last_login_at": last_login_value}).eq("id", user_id).execute()
        return last_login_value
    except Exception as update_error:  # pragma: no cover - external service errors
        message = getattr(update_error, "message", None) or str(update_error)
        print(f"[WARN] Failed to update last_login_at ({context}): {message}")
        if "last_login_at" in message and "schema cache" in message:
            LAST_LOGIN_FIELD_AVAILABLE = False
            print("[INFO] Disabling last_login_at updates until column is available.")
        return None


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
    if "x_connection_status" in user_info:
        has_x_connection = bool(user_info.get("x_connection_status"))
    else:
        supabase = get_supabase()
        x_connection = (
            supabase
            .table("user_x_connections")
            .select("user_id")
            .eq("user_id", user_info["id"])
            .maybe_single()
            .execute()
        )
        has_x_connection = bool(x_connection and x_connection.data)
    preferred_locale = user_info.get("preferred_locale") or "ja"
    if isinstance(preferred_locale, str):
        preferred_locale = preferred_locale.strip().lower() or "ja"
    else:
        preferred_locale = "ja"
    return UserResponse(
        id=user_info["id"],
        email=user_info["email"],
        username=user_info["username"],
        user_type=user_info.get("user_type", "seller"),
        point_balance=user_info.get("point_balance", 0),
        created_at=created_at,
        bio=user_info.get("bio"),
        sns_url=user_info.get("sns_url"),
        line_url=user_info.get("line_url"),
        profile_image_url=user_info.get("profile_image_url"),
        last_login_at=user_info.get("last_login_at"),
        x_connection_status=has_x_connection,
        preferred_locale=preferred_locale if preferred_locale in {"ja", "en"} else "ja",
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
            "point_balance": 0,
            "bio": None,
            "sns_url": None,
            "line_url": None,
            "profile_image_url": None,
            "last_login_at": None,
            "preferred_locale": "ja",
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

        last_login_value = update_last_login_timestamp(supabase, user_info["id"], "password")
        if last_login_value:
            user_info["last_login_at"] = last_login_value
        
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
        print("❌ GOOGLE_CLIENT_ID が設定されていません")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuthの設定が完了していません"
        )

    print(f"🔐 Google認証開始 - Client ID: {settings.google_client_id[:20]}...")
    
    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            settings.google_client_id
        )
        print(f"✅ IDトークン検証成功 - Email: {id_info.get('email')}, Verified: {id_info.get('email_verified')}")
    except ValueError as exc:
        print(f"❌ IDトークン検証失敗: {str(exc)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google認証に失敗しました: {str(exc)}"
        ) from exc

    email = id_info.get("email")
    email_verified = id_info.get("email_verified", False)

    if not email:
        print("❌ メールアドレスが取得できませんでした")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Googleアカウントのメールアドレスを取得できませんでした"
        )

    if not email_verified:
        print(f"❌ メールアドレス未確認: {email}")
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

    last_login_value = update_last_login_timestamp(supabase, user_info["id"], "Google")
    if last_login_value:
        user_info["last_login_at"] = last_login_value

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
        x_connection = (
            supabase
            .table("user_x_connections")
            .select("user_id")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        user_info["x_connection_status"] = bool(x_connection and x_connection.data)
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

        def normalize_optional_text(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            stripped = value.strip()
            return stripped or None
        
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
        
        if data.bio is not None:
            update_data["bio"] = normalize_optional_text(data.bio)

        if data.sns_url is not None:
            update_data["sns_url"] = normalize_optional_text(data.sns_url)

        if data.line_url is not None:
            update_data["line_url"] = normalize_optional_text(data.line_url)

        if data.profile_image_url is not None:
            update_data["profile_image_url"] = normalize_optional_text(data.profile_image_url)

        if data.preferred_locale is not None:
            update_data["preferred_locale"] = data.preferred_locale

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
