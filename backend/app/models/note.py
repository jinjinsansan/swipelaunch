from __future__ import annotations

from typing import List, Optional, Literal, Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field, validator, root_validator


class NoteBlock(BaseModel):
    """Content block for note articles."""

    id: Optional[str] = None
    type: str = Field(..., description="ブロックタイプ（paragraph, heading等）")
    access: Literal["public", "paid"] = Field("public", description="閲覧権限")
    data: dict = Field(default_factory=dict, description="ブロックデータ")


class NoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    cover_image_url: Optional[str] = Field(None, description="カバー画像URL")
    excerpt: Optional[str] = Field(None, description="一覧表示用の概要")
    content_blocks: List[NoteBlock] = Field(default_factory=list)
    is_paid: bool = Field(False, description="有料記事フラグ")
    price_points: Optional[int] = Field(None, ge=0, description="有料記事の価格（ポイント）")
    price_jpy: Optional[int] = Field(None, ge=0, description="有料記事の価格（日本円）")
    allow_point_purchase: bool = Field(True, description="ポイントでの購入を許可するか")
    allow_jpy_purchase: bool = Field(False, description="日本円決済を許可するか")
    tax_rate: Optional[float] = Field(10.0, ge=0, le=100, description="税込計算用の税率（%）")
    tax_inclusive: bool = Field(True, description="税込表示かどうか")
    categories: List[str] = Field(default_factory=list, description="カテゴリー一覧")
    salon_ids: List[str] = Field(default_factory=list, description="無料閲覧を許可するサロンID一覧")

    @validator("content_blocks")
    def validate_blocks(cls, value: List[NoteBlock]) -> List[NoteBlock]:
        if not value:
            raise ValueError("content_blocks は少なくとも1件必要です")
        return value

    @validator("price_points", always=True)
    def validate_price(cls, value: Optional[int], values: dict) -> Optional[int]:
        is_paid = values.get("is_paid")
        allow_point = values.get("allow_point_purchase", True)
        if is_paid and allow_point:
            if value is None or value <= 0:
                raise ValueError("有料記事の価格は1ポイント以上で指定してください")
        if not allow_point:
            return 0
        return value if value is not None else 0

    @validator("price_jpy", always=True)
    def validate_price_jpy(cls, value: Optional[int], values: dict) -> Optional[int]:
        is_paid = values.get("is_paid")
        allow_jpy = values.get("allow_jpy_purchase", False)
        if is_paid and allow_jpy:
            if value is None or value <= 0:
                raise ValueError("有料記事の日本円価格を設定してください")
        if not allow_jpy:
            return None
        return value

    @validator("categories", pre=True, always=True)
    def normalize_categories(cls, value: Optional[List[str]]) -> List[str]:
        if not value:
            return []
        if not isinstance(value, list):
            raise ValueError("categories は配列で指定してください")
        normalized: List[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("カテゴリは文字列で指定してください")
            slug = raw.strip()
            if not slug:
                continue
            normalized.append(slug[:40])
        if len(normalized) > 8:
            raise ValueError("カテゴリは最大8件まで指定できます")
        return normalized

    @validator("salon_ids", pre=True, always=True)
    def normalize_salons(cls, value: Optional[List[str]]) -> List[str]:
        if not value:
            return []
        if not isinstance(value, list):
            raise ValueError("salon_ids は配列で指定してください")
        sanitized: List[str] = []
        seen = set()
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("サロンIDは文字列で指定してください")
            key = raw.strip()
            if not key or key in seen:
                continue
            if len(key) > 64:
                raise ValueError("サロンIDが長すぎます")
            sanitized.append(key)
            seen.add(key)
        return sanitized


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    cover_image_url: Optional[str] = None
    excerpt: Optional[str] = None
    content_blocks: Optional[List[NoteBlock]] = None
    is_paid: Optional[bool] = None
    price_points: Optional[int] = Field(None, ge=0)
    price_jpy: Optional[int] = Field(None, ge=0)
    allow_point_purchase: Optional[bool] = None
    allow_jpy_purchase: Optional[bool] = None
    tax_rate: Optional[float] = Field(None, ge=0, le=100)
    tax_inclusive: Optional[bool] = None
    categories: Optional[List[str]] = Field(None, description="カテゴリー一覧")
    salon_ids: Optional[List[str]] = Field(None, description="無料閲覧を許可するサロンID一覧")

    @validator("price_points")
    def validate_price(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("価格は0以上のポイントで指定してください")
        return value

    @validator("price_jpy")
    def validate_price_jpy(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("日本円価格は0以上で指定してください")
        return value

    @validator("categories")
    def normalize_categories(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("categories は配列で指定してください")
        normalized: List[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("カテゴリは文字列で指定してください")
            slug = raw.strip()
            if not slug:
                continue
            normalized.append(slug[:40])
        if len(normalized) > 8:
            raise ValueError("カテゴリは最大8件まで指定できます")
        return normalized

    @validator("salon_ids")
    def normalize_salons(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("salon_ids は配列で指定してください")
        sanitized: List[str] = []
        seen = set()
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("サロンIDは文字列で指定してください")
            key = raw.strip()
            if not key or key in seen:
                continue
            if len(key) > 64:
                raise ValueError("サロンIDが長すぎます")
            sanitized.append(key)
            seen.add(key)
        return sanitized


class NoteSummaryResponse(BaseModel):
    id: str
    author_id: str
    title: str
    slug: str
    cover_image_url: Optional[str] = None
    excerpt: Optional[str] = None
    is_paid: bool
    price_points: int
    price_jpy: Optional[int] = None
    allow_point_purchase: bool
    allow_jpy_purchase: bool
    tax_rate: Optional[float] = None
    tax_inclusive: bool
    status: Literal["draft", "published"]
    published_at: Optional[datetime] = None
    updated_at: datetime
    categories: List[str] = Field(default_factory=list)
    allow_share_unlock: Optional[bool] = False
    official_share_tweet_id: Optional[str] = None
    official_share_tweet_url: Optional[str] = None
    official_share_x_user_id: Optional[str] = None
    official_share_x_username: Optional[str] = None
    official_share_set_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NoteDetailResponse(NoteSummaryResponse):
    content_blocks: List[Any] = Field(default_factory=list)
    salon_access_ids: List[str] = Field(default_factory=list)


class NoteListResponse(BaseModel):
    data: List[NoteSummaryResponse]
    total: int
    limit: int
    offset: int


class PublicNoteSummary(BaseModel):
    id: str
    title: str
    slug: str
    cover_image_url: Optional[str] = None
    excerpt: Optional[str] = None
    is_paid: bool
    price_points: int
    price_jpy: Optional[int] = None
    allow_point_purchase: bool
    allow_jpy_purchase: bool
    tax_rate: Optional[float] = None
    tax_inclusive: bool
    author_username: Optional[str] = None
    published_at: Optional[datetime] = None
    categories: List[str] = Field(default_factory=list)
    allow_share_unlock: Optional[bool] = False
    official_share_tweet_id: Optional[str] = None
    official_share_tweet_url: Optional[str] = None
    official_share_x_username: Optional[str] = None


class PublicNoteListResponse(BaseModel):
    data: List[PublicNoteSummary]
    total: int
    limit: int
    offset: int


class PublicNoteDetailResponse(BaseModel):
    id: str
    title: str
    slug: str
    author_id: str
    author_username: Optional[str] = None
    cover_image_url: Optional[str] = None
    excerpt: Optional[str] = None
    is_paid: bool
    price_points: int
    price_jpy: Optional[int] = None
    allow_point_purchase: bool
    allow_jpy_purchase: bool
    tax_rate: Optional[float] = None
    tax_inclusive: bool
    has_access: bool
    content_blocks: List[Any] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    categories: List[str] = Field(default_factory=list)
    allow_share_unlock: Optional[bool] = False
    official_share_tweet_id: Optional[str] = None
    official_share_tweet_url: Optional[str] = None
    official_share_x_username: Optional[str] = None
    salon_access_ids: List[str] = Field(default_factory=list)


class NotePurchaseResponse(BaseModel):
    note_id: str
    points_spent: int
    amount_jpy: Optional[int] = None
    remaining_points: int
    payment_method: Literal["points", "yen"] = "points"
    purchased_at: Optional[datetime] = None
    payment_status: Literal["completed", "pending"] = "completed"
    checkout_url: Optional[str] = None
    external_id: Optional[str] = None


class NoteMetricsTopNote(BaseModel):
    note_id: str
    title: str
    slug: Optional[str] = None
    purchase_count: int
    points_earned: int


class NoteMetricsResponse(BaseModel):
    total_notes: int
    published_notes: int
    draft_notes: int
    paid_notes: int
    free_notes: int
    total_sales_count: int
    total_sales_points: int
    monthly_sales_count: int
    monthly_sales_points: int
    recent_published_count: int
    average_paid_price: int
    latest_published_at: Optional[datetime] = None
    top_categories: List[str] = Field(default_factory=list)
    top_note: Optional[NoteMetricsTopNote] = None


class OfficialShareSetupRequest(BaseModel):
    tweet_id: Optional[str] = Field(None, min_length=1, max_length=64)
    tweet_url: Optional[str] = Field(None, max_length=512)

    @root_validator(pre=True)
    def ensure_identifier(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        tweet_id = values.get("tweet_id")
        tweet_url = values.get("tweet_url")
        if not tweet_id and not tweet_url:
            raise ValueError("tweet_id か tweet_url のいずれかを指定してください")
        return values


class OfficialShareConfigResponse(BaseModel):
    note_id: str
    tweet_id: Optional[str] = None
    tweet_url: Optional[str] = None
    tweet_text: Optional[str] = None
    author_x_user_id: Optional[str] = None
    author_x_username: Optional[str] = None
    configured_at: Optional[datetime] = None
