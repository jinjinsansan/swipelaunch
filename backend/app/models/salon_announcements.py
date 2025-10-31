"""Pydantic models for salon announcements."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SalonAnnouncementResponse(BaseModel):
    id: str
    salon_id: str
    author_id: str
    title: str
    body: str
    is_pinned: bool
    is_published: bool
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class SalonAnnouncementListResponse(BaseModel):
    data: List[SalonAnnouncementResponse]
    total: int
    limit: int
    offset: int


class SalonAnnouncementCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)
    is_pinned: bool = False
    is_published: bool = True
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class SalonAnnouncementUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    body: Optional[str] = Field(None, min_length=1, max_length=5000)
    is_pinned: Optional[bool] = None
    is_published: Optional[bool] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
