"""Pydantic models for salon asset library."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SalonAssetResponse(BaseModel):
    id: str
    salon_id: str
    uploader_id: str
    asset_type: str
    title: Optional[str]
    description: Optional[str]
    file_url: str
    thumbnail_url: Optional[str]
    content_type: str
    file_size: int
    visibility: str
    created_at: datetime
    updated_at: datetime


class SalonAssetListResponse(BaseModel):
    data: List[SalonAssetResponse]
    total: int
    limit: int
    offset: int


class SalonAssetMetadata(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    asset_type: Optional[str] = Field(default=None, max_length=32)
    visibility: Optional[str] = Field(default="MEMBERS", max_length=32)
