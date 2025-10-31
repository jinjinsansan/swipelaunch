"""Pydantic models for aggregated purchase history."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PurchaseHistorySummary(BaseModel):
    product_purchases: int
    note_purchases: int
    active_salon_memberships: int


class PurchaseHistoryProduct(BaseModel):
    transaction_id: str
    product_id: Optional[str]
    product_title: Optional[str]
    amount_points: int
    purchased_at: datetime
    description: Optional[str] = None
    seller_username: Optional[str] = None
    seller_display_name: Optional[str] = None
    seller_profile_image_url: Optional[str] = None
    lp_slug: Optional[str] = None


class PurchaseHistoryNote(BaseModel):
    purchase_id: str
    note_id: str
    note_title: Optional[str]
    note_slug: Optional[str]
    cover_image_url: Optional[str]
    author_username: Optional[str]
    author_display_name: Optional[str]
    points_spent: int
    purchased_at: datetime


class PurchaseHistorySalon(BaseModel):
    membership_id: str
    salon_id: str
    salon_title: Optional[str]
    salon_category: Optional[str]
    salon_thumbnail_url: Optional[str]
    owner_username: Optional[str]
    owner_display_name: Optional[str]
    plan_label: Optional[str]
    plan_points: Optional[int]
    plan_usd_amount: Optional[float]
    joined_at: datetime
    status: str
    next_charge_at: Optional[datetime] = None
    last_charged_at: Optional[datetime] = None


class PurchaseHistoryResponse(BaseModel):
    summary: PurchaseHistorySummary
    products: List[PurchaseHistoryProduct]
    notes: List[PurchaseHistoryNote]
    active_salons: List[PurchaseHistorySalon]
