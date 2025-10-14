from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import datetime

# LP作成リクエスト
class LPCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="LPタイトル")
    slug: str = Field(..., min_length=1, max_length=100, description="URL用スラッグ")
    swipe_direction: Literal["vertical", "horizontal"] = Field(default="vertical", description="スワイプ方向")
    is_fullscreen: bool = Field(default=False, description="全画面表示")

# LP更新リクエスト
class LPUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    swipe_direction: Optional[Literal["vertical", "horizontal"]] = None
    is_fullscreen: Optional[bool] = None
    status: Optional[Literal["draft", "published", "archived"]] = None

# LPステップモデル
class LPStepResponse(BaseModel):
    id: str
    lp_id: str
    step_order: int
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    animation_type: Optional[str] = None
    step_views: int = 0
    step_exits: int = 0
    block_type: Optional[str] = None
    content_data: Optional[dict] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# CTAモデル
class CTAResponse(BaseModel):
    id: str
    lp_id: str
    step_id: Optional[str] = None
    cta_type: str
    button_image_url: str
    button_position: str = "bottom"
    link_url: Optional[str] = None
    is_required: bool = False
    click_count: int = 0
    created_at: datetime
    
    class Config:
        from_attributes = True

# LPレスポンス（基本情報のみ）
class LPResponse(BaseModel):
    id: str
    seller_id: str
    title: str
    slug: str
    status: str
    swipe_direction: str
    is_fullscreen: bool
    total_views: int = 0
    total_cta_clicks: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# LP詳細レスポンス（ステップとCTA含む）
class LPDetailResponse(BaseModel):
    id: str
    seller_id: str
    title: str
    slug: str
    status: str
    swipe_direction: str
    is_fullscreen: bool
    total_views: int = 0
    total_cta_clicks: int = 0
    steps: List[LPStepResponse] = []
    ctas: List[CTAResponse] = []
    created_at: datetime
    updated_at: datetime
    public_url: str
    
    class Config:
        from_attributes = True

# ステップ追加リクエスト
class StepCreateRequest(BaseModel):
    step_order: int = Field(..., ge=0, description="ステップ順序（0から開始）")
    image_url: Optional[str] = Field(None, description="画像URL")
    video_url: Optional[str] = Field(None, description="動画URL（オプション）")
    animation_type: Optional[str] = Field(None, description="アニメーションタイプ")
    block_type: Optional[str] = Field(None, description="ブロックタイプ")
    content_data: Optional[dict] = Field(None, description="ブロックコンテンツデータ")

# ステップ更新リクエスト
class StepUpdateRequest(BaseModel):
    step_order: Optional[int] = Field(None, ge=0)
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    animation_type: Optional[str] = None
    block_type: Optional[str] = None
    content_data: Optional[dict] = None

# CTA追加リクエスト
class CTACreateRequest(BaseModel):
    step_id: Optional[str] = Field(None, description="特定ステップに紐付ける場合のステップID（nullで全体共通）")
    cta_type: Literal["link", "form", "product", "newsletter", "line"] = Field(..., description="CTAタイプ")
    button_image_url: str = Field(..., description="ボタン画像URL")
    button_position: Literal["top", "bottom", "floating"] = Field(default="bottom", description="ボタン位置")
    link_url: Optional[str] = Field(None, description="リンク先URL")
    is_required: bool = Field(default=False, description="次へ進むのに必須か")

# CTA更新リクエスト
class CTAUpdateRequest(BaseModel):
    cta_type: Optional[Literal["link", "form", "product", "newsletter", "line"]] = None
    button_image_url: Optional[str] = None
    button_position: Optional[Literal["top", "bottom", "floating"]] = None
    link_url: Optional[str] = None
    is_required: Optional[bool] = None

# LP一覧レスポンス
class LPListResponse(BaseModel):
    data: List[LPResponse]
    total: int
    limit: int
    offset: int
