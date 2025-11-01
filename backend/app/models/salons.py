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
    monthly_price_jpy: Optional[int] = Field(None, ge=0, description="日本円での月額価格")
    allow_point_subscription: bool = Field(True, description="ポイントサブスクを許可するか")
    allow_jpy_subscription: bool = Field(False, description="日本円サブスクを許可するか")
    tax_rate: Optional[float] = Field(10.0, ge=0, le=100)
    tax_inclusive: bool = Field(True)


class SalonUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=2000)
    thumbnail_url: Optional[str] = Field(None, max_length=1024)
    is_active: Optional[bool] = None
    lp_id: Optional[str] = Field(None, description="Link to LP that will redirect to this salon")
    monthly_price_jpy: Optional[int] = Field(None, ge=0)
    allow_point_subscription: Optional[bool] = None
    allow_jpy_subscription: Optional[bool] = None
    tax_rate: Optional[float] = Field(None, ge=0, le=100)
    tax_inclusive: Optional[bool] = None


class SalonResponse(BaseModel):
    id: str
    owner_id: str
    title: str
    description: Optional[str]
    thumbnail_url: Optional[str]
    subscription_plan_id: str
    subscription_external_id: Optional[str]
    monthly_price_jpy: Optional[int] = None
    allow_point_subscription: bool
    allow_jpy_subscription: bool
    tax_rate: Optional[float] = None
    tax_inclusive: bool
    is_active: bool
    member_count: int = 0
    lp_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SalonListResponse(BaseModel):
    data: List[SalonResponse]


class SalonPublicListItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    thumbnail_url: Optional[str]
    category: Optional[str]
    owner_username: str
    owner_display_name: Optional[str]
    owner_profile_image_url: Optional[str]
    plan_label: str
    plan_points: int
    plan_usd_amount: float
    monthly_price_jpy: Optional[int]
    allow_jpy_subscription: bool
    created_at: datetime


class SalonPublicListResponse(BaseModel):
    data: List[SalonPublicListItem]
    total: int
    limit: int
    offset: int


class SalonPublicOwner(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    profile_image_url: Optional[str] = None


class SalonPublicPlan(BaseModel):
    key: str
    label: str
    points: int
    usd_amount: float
    subscription_plan_id: str
    monthly_price_jpy: Optional[int] = None
    allow_point_subscription: bool = True
    allow_jpy_subscription: bool = False
    tax_rate: Optional[float] = None
    tax_inclusive: bool = True


class SalonPublicResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    thumbnail_url: Optional[str]
    is_active: bool
    owner: SalonPublicOwner
    plan: SalonPublicPlan
    member_count: int
    is_member: bool
    membership_status: Optional[str] = None
    allow_point_subscription: bool
    allow_jpy_subscription: bool
    created_at: datetime
    updated_at: datetime


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
