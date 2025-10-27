from __future__ import annotations

from typing import List, Optional, Literal, Any
from datetime import datetime

from pydantic import BaseModel, Field, validator


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

    @validator("content_blocks")
    def validate_blocks(cls, value: List[NoteBlock]) -> List[NoteBlock]:
        if not value:
            raise ValueError("content_blocks は少なくとも1件必要です")
        return value

    @validator("price_points", always=True)
    def validate_price(cls, value: Optional[int], values: dict) -> Optional[int]:
        if values.get("is_paid"):
            if value is None or value <= 0:
                raise ValueError("有料記事の価格は1ポイント以上で指定してください")
        return value if value is not None else 0


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    cover_image_url: Optional[str] = None
    excerpt: Optional[str] = None
    content_blocks: Optional[List[NoteBlock]] = None
    is_paid: Optional[bool] = None
    price_points: Optional[int] = Field(None, ge=0)

    @validator("price_points")
    def validate_price(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("価格は1以上のポイントで指定してください")
        return value


class NoteSummaryResponse(BaseModel):
    id: str
    author_id: str
    title: str
    slug: str
    cover_image_url: Optional[str] = None
    excerpt: Optional[str] = None
    is_paid: bool
    price_points: int
    status: Literal["draft", "published"]
    published_at: Optional[datetime] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteDetailResponse(NoteSummaryResponse):
    content_blocks: List[Any] = Field(default_factory=list)


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
    author_username: Optional[str] = None
    published_at: Optional[datetime] = None


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
    has_access: bool
    content_blocks: List[Any] = Field(default_factory=list)
    published_at: Optional[datetime] = None


class NotePurchaseResponse(BaseModel):
    note_id: str
    points_spent: int
    remaining_points: int
    purchased_at: datetime
