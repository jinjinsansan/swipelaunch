"""Pydantic models for subscription APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SubscriptionPlanResponse(BaseModel):
    """Represents an available subscription plan."""

    plan_key: str = Field(..., description="Unique plan identifier used internally")
    label: str = Field(..., description="Display label for the plan")
    points: int = Field(..., ge=0, description="Number of points granted per billing cycle")
    usd_amount: float = Field(..., ge=0, description="USD amount charged per cycle")
    subscription_plan_id: str = Field(..., description="ONE.lat subscription plan identifier")


class SubscriptionPlanListResponse(BaseModel):
    data: List[SubscriptionPlanResponse]


class SubscriptionCheckoutRequest(BaseModel):
    """Checkout creation request payload."""

    plan_key: str = Field(..., description="Subscription plan key")
    seller_id: Optional[str] = Field(
        default=None,
        description="Optional seller identifier for multi-seller attribution",
    )
    seller_username: Optional[str] = Field(
        default=None,
        description="Seller username for display after redirect",
    )
    success_path: Optional[str] = Field(
        default=None,
        description="Frontend path to redirect upon success (overrides default)",
    )
    error_path: Optional[str] = Field(
        default=None,
        description="Frontend path to redirect upon failure (overrides default)",
    )
    salon_id: Optional[str] = Field(
        default=None,
        description="Salon identifier to link the subscription with an online community",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to persist with the subscription",
    )


class SubscriptionCheckoutResponse(BaseModel):
    checkout_url: str
    checkout_preference_id: str
    external_id: str


class UserSubscriptionResponse(BaseModel):
    id: str
    plan_key: str
    label: str
    status: str
    points_per_cycle: int
    usd_amount: float
    subscription_plan_id: str
    recurrent_payment_id: Optional[str] = None
    next_charge_at: Optional[datetime] = None
    last_charge_at: Optional[datetime] = None
    last_event_type: Optional[str] = None
    seller_id: Optional[str] = None
    seller_username: Optional[str] = None
    salon_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    cancelable: bool = True
    created_at: datetime
    updated_at: datetime


class UserSubscriptionListResponse(BaseModel):
    data: List[UserSubscriptionResponse]


class SubscriptionCancelResponse(BaseModel):
    id: str
    status: str
    canceled_at: datetime
