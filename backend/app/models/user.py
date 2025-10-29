from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from typing import Optional, Literal
from datetime import datetime
from urllib.parse import urlparse

# ユーザー登録リクエスト
class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="パスワード（8文字以上）")
    username: str = Field(..., min_length=3, max_length=100, description="ユーザー名")
    user_type: Literal["seller", "buyer"] = Field(..., description="ユーザータイプ")

# ログインリクエスト
class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str

# ユーザーレスポンス
class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    user_type: str
    point_balance: int
    created_at: datetime
    bio: Optional[str] = None
    sns_url: Optional[str] = None
    line_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    last_login_at: Optional[datetime] = None
    x_connection_status: bool = False
    
    class Config:
        from_attributes = True

# 認証レスポンス（トークン付き）
class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

# トークンペイロード
class TokenPayload(BaseModel):
    sub: str  # user_id
    exp: int  # expiration time
    iat: int  # issued at

# プロフィール更新リクエスト
class ProfileUpdateRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=20, pattern="^[a-zA-Z0-9_]+$", description="ユーザー名（3-20文字、英数字とアンダースコアのみ）")
    bio: Optional[str] = Field(None, max_length=600, description="プロフィールの自己紹介（最大600文字）")
    sns_url: Optional[str] = Field(None, max_length=2048, description="SNSプロフィールURL")
    line_url: Optional[str] = Field(None, max_length=2048, description="公式LINEのURL")
    profile_image_url: Optional[str] = Field(None, max_length=2048, description="プロフィール画像URL")

    model_config = ConfigDict(extra="forbid")

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        sanitized = value.strip()
        return sanitized if sanitized else ""

    @field_validator("sns_url", "line_url", "profile_image_url")
    @classmethod
    def validate_optional_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        sanitized = value.strip()
        if sanitized == "":
            return ""
        parsed = urlparse(sanitized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("有効なURLを入力してください（httpまたはhttps）")
        return sanitized


class GoogleAuthRequest(BaseModel):
    credential: str = Field(..., description="Google IDトークン（credential）")
