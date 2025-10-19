from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import datetime

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
