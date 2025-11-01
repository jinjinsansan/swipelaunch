"""Pydantic models for seller sales history."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel


class SalesSummary(BaseModel):
    product_orders: int
    note_orders: int
    salon_memberships: int
    total_points_revenue: int
    total_yen_revenue: int


class SalesProductRecord(BaseModel):
    sale_id: str
    product_id: Optional[str]
    product_title: Optional[str]
    buyer_id: Optional[str]
    buyer_username: Optional[str]
    buyer_profile_image_url: Optional[str]
    payment_method: Literal["points", "yen"]
    amount_points: int
    amount_jpy: Optional[int] = None
    purchased_at: datetime
    lp_slug: Optional[str]
    description: Optional[str]


class SalesNoteRecord(BaseModel):
    sale_id: str
    note_id: str
    note_title: Optional[str]
    note_slug: Optional[str]
    buyer_id: Optional[str]
    buyer_username: Optional[str]
    buyer_profile_image_url: Optional[str]
    payment_method: Literal["points", "yen"]
    points_spent: int
    amount_jpy: Optional[int] = None
    purchased_at: datetime


class SalesSalonRecord(BaseModel):
    membership_id: str
    salon_id: str
    salon_title: Optional[str]
    buyer_id: Optional[str]
    buyer_username: Optional[str]
    buyer_profile_image_url: Optional[str]
    status: str
    joined_at: datetime
    next_charge_at: Optional[datetime]
    last_charged_at: Optional[datetime]


class SalesHistoryResponse(BaseModel):
    summary: SalesSummary
    products: List[SalesProductRecord]
    notes: List[SalesNoteRecord]
    salons: List[SalesSalonRecord]
