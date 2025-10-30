"""Pydantic models for salon management."""

from __future__ import annotations

from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class SalonCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=2000)
    thumbnail_url: Optional[str] = Field(None, max_length=1024)
    subscription_plan_id: str = Field(..., min_length=1, max_length=64)
    subscription_external_id: Optional[str] = Field(None, max_length=128)


class SalonUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=2000)
    thumbnail_url: Optional[str] = Field(None, max_length=1024)
    is_active: Optional[bool] = None


class SalonResponse(BaseModel):
    id: str
    owner_id: str
    title: str
    description: Optional[str]
    thumbnail_url: Optional[str]
    subscription_plan_id: str
    subscription_external_id: Optional[str]
    is_active: bool
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class SalonListResponse(BaseModel):
    data: List[SalonResponse]


class SalonMemberResponse(BaseModel):
    id: str
    salon_id: str
    user_id: str
    status: str
    recurrent_payment_id: Optional[str]
    subscription_session_external_id: Optional[str]
    last_event_type: Optional[str]
    joined_at: datetime
    last_charged_at: Optional[datetime]
    next_charge_at: Optional[datetime]
    canceled_at: Optional[datetime]


class SalonMemberListResponse(BaseModel):
    data: List[SalonMemberResponse]
    total: int
    limit: int
    offset: int


class NoteSalonAccessRequest(BaseModel):
    salon_ids: List[str] = Field(default_factory=list)


class NoteSalonAccessResponse(BaseModel):
    salon_ids: List[str] = Field(default_factory=list)
