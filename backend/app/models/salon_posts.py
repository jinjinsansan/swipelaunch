"""Pydantic models for salon community posts."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SalonPostCreateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    body: str = Field(..., min_length=1)
    is_published: bool = Field(default=True)


class SalonPostUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    body: Optional[str] = Field(None, min_length=1)
    is_published: Optional[bool] = None
    is_pinned: Optional[bool] = None


class SalonPostResponse(BaseModel):
    id: str
    salon_id: str
    user_id: str
    title: Optional[str]
    body: str
    is_pinned: bool
    is_published: bool
    like_count: int
    comment_count: int
    liked_by_me: bool
    created_at: datetime
    updated_at: datetime
    author_username: Optional[str]


class SalonPostListResponse(BaseModel):
    data: List[SalonPostResponse]
    total: int
    limit: int
    offset: int


class SalonCommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=1)
    parent_id: Optional[str] = None


class SalonCommentUpdateRequest(BaseModel):
    body: str = Field(..., min_length=1)


class SalonCommentResponse(BaseModel):
    id: str
    post_id: str
    user_id: str
    body: str
    parent_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    author_username: Optional[str]


class SalonCommentListResponse(BaseModel):
    data: List[SalonCommentResponse]
    total: int
    limit: int
    offset: int


class SalonPostLikeResponse(BaseModel):
    post_id: str
    user_id: str
    liked: bool
    like_count: int
