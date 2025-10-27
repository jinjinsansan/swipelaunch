from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class LINEWebhookEvent(BaseModel):
    """LINE Webhook イベント"""
    type: str
    timestamp: int
    source: dict
    replyToken: Optional[str] = None
    message: Optional[dict] = None

class LINEWebhookRequest(BaseModel):
    """LINE Webhook リクエスト"""
    destination: str
    events: list[LINEWebhookEvent]

class LINEUserProfile(BaseModel):
    """LINE ユーザープロフィール"""
    userId: str
    displayName: str
    pictureUrl: Optional[str] = None
    statusMessage: Optional[str] = None

class LineConnectionResponse(BaseModel):
    """LINE連携状態レスポンス"""
    id: str
    user_id: str
    line_user_id: str
    display_name: Optional[str]
    picture_url: Optional[str]
    connected_at: datetime
    bonus_awarded: bool
    bonus_points: Optional[int]
    bonus_awarded_at: Optional[datetime]

class LineBonusSettingsResponse(BaseModel):
    """LINEボーナス設定レスポンス"""
    id: str
    bonus_points: int
    is_enabled: bool
    description: str
    line_add_url: str
    created_at: datetime
    updated_at: datetime

class LineBonusSettingsUpdate(BaseModel):
    """LINEボーナス設定更新リクエスト"""
    bonus_points: Optional[int] = Field(None, ge=0, le=10000, description="ボーナスポイント数（0-10000）")
    is_enabled: Optional[bool] = Field(None, description="有効/無効")
    description: Optional[str] = Field(None, max_length=500, description="説明文")
    line_add_url: Optional[str] = Field(None, description="LINE追加URL")

class LineLinkStatusResponse(BaseModel):
    """LINE連携状態とボーナス情報"""
    is_connected: bool
    bonus_settings: Optional[LineBonusSettingsResponse]
    connection: Optional[LineConnectionResponse]

class LineLinkTokenResponse(BaseModel):
    """LINE連携トークンレスポンス"""
    token: str
    line_add_url: str
    expires_at: datetime
