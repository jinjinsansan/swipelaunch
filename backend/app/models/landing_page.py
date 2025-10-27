from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict, Any
from datetime import datetime

# LP作成リクエスト
class LPCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="LPタイトル")
    slug: str = Field(..., min_length=1, max_length=100, description="URL用スラッグ")
    swipe_direction: Literal["vertical", "horizontal"] = Field(default="vertical", description="スワイプ方向")
    is_fullscreen: bool = Field(default=False, description="全画面表示")
    product_id: Optional[str] = Field(None, description="紐づける商品ID")
    show_swipe_hint: bool = Field(default=False, description="スワイプヒントを表示するか")
    fullscreen_media: bool = Field(default=False, description="メディアを全画面表示するか")
    floating_cta: bool = Field(default=False, description="CTAをフローティング表示するか")
    meta_title: Optional[str] = Field(None, description="OGPタイトル")
    meta_description: Optional[str] = Field(None, description="OGPディスクリプション")
    meta_image_url: Optional[str] = Field(None, description="OGP画像URL")
    meta_site_name: Optional[str] = Field(None, description="OGPサイト名")
    custom_theme_hex: Optional[str] = Field(None, description="カスタムテーマのベースカラー（HEX）")
    custom_theme_shades: Optional[dict] = Field(None, description="カスタムテーマの11段階シェード")

# LP更新リクエスト
class LPUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    swipe_direction: Optional[Literal["vertical", "horizontal"]] = None
    is_fullscreen: Optional[bool] = None
    status: Optional[Literal["draft", "published", "archived"]] = None
    product_id: Optional[str] = None
    show_swipe_hint: Optional[bool] = None
    fullscreen_media: Optional[bool] = None
    floating_cta: Optional[bool] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    meta_image_url: Optional[str] = None
    meta_site_name: Optional[str] = None
    custom_theme_hex: Optional[str] = None
    custom_theme_shades: Optional[dict] = None

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

# Owner情報（seller情報を表示するため）
class OwnerInfo(BaseModel):
    username: str
    email: str
    
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
    show_swipe_hint: bool = False
    fullscreen_media: bool = False
    floating_cta: bool = False
    total_views: int = 0
    total_cta_clicks: int = 0
    product_id: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    meta_image_url: Optional[str] = None
    meta_site_name: Optional[str] = None
    custom_theme_hex: Optional[str] = None
    custom_theme_shades: Optional[dict] = None
    owner: Optional[OwnerInfo] = None  # seller情報（JOINで取得）
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
    show_swipe_hint: bool = False
    fullscreen_media: bool = False
    floating_cta: bool = False
    total_views: int = 0
    total_cta_clicks: int = 0
    product_id: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    meta_image_url: Optional[str] = None
    meta_site_name: Optional[str] = None
    custom_theme_hex: Optional[str] = None
    custom_theme_shades: Optional[dict] = None
    owner: Optional[OwnerInfo] = None  # seller情報（JOINで取得）
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


class LPStepUpsertRequest(BaseModel):
    id: Optional[str] = None
    step_order: int
    block_type: Optional[str] = None
    content_data: Dict[str, Any] = Field(default_factory=dict)
    image_url: Optional[str] = None
    video_url: Optional[str] = None


class LPStepsBulkUpdateRequest(BaseModel):
    steps: List[LPStepUpsertRequest]


class LPStepsBulkUpdateResponse(BaseModel):
    steps: List[LPStepResponse]
