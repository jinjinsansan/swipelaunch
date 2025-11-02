from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PayoutSettings(BaseModel):
    user_id: str
    usdt_address: str
    address_label: Optional[str] = None
    preferred_network: str = Field(default="TRC20")
    payout_cycle_days: int = 10
    address_verified_at: Optional[datetime] = None
    payout_note: Optional[str] = None
    last_reviewed_at: Optional[datetime] = None
    reviewer_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PayoutSettingsUpsertRequest(BaseModel):
    usdt_address: str
    address_label: Optional[str] = None
    preferred_network: Optional[str] = Field(default="TRC20")
    payout_note: Optional[str] = None


class PayoutLineItem(BaseModel):
    id: str
    payout_id: str
    source_type: str
    source_id: str
    occurred_at: Optional[datetime] = None
    description: Optional[str] = None
    gross_amount_usd: Optional[float] = None
    gross_amount_jpy: Optional[float] = None
    gross_amount_points: Optional[int] = None
    gross_amount_usdt: Optional[float] = None
    fee_amount_usd: Optional[float] = None
    fee_amount_usdt: Optional[float] = None
    net_amount_usd: Optional[float] = None
    net_amount_usdt: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class PayoutEvent(BaseModel):
    id: str
    payout_id: str
    event_type: str
    title: Optional[str] = None
    body: Optional[str] = None
    actor_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PayoutLedgerEntry(BaseModel):
    id: str
    seller_id: str
    seller_username: Optional[str] = None
    seller_email: Optional[str] = None
    period_start: datetime
    period_end: datetime
    settlement_due_at: datetime
    funds_expected_at: Optional[datetime] = None
    payout_cycle_days: int
    one_lat_batch_id: Optional[str] = None
    currency: str
    gross_amount_usd: float
    gross_amount_usdt: Optional[float] = None
    gross_amount_points: Optional[int] = None
    fee_amount_usd: Optional[float] = None
    fee_amount_usdt: Optional[float] = None
    net_amount_usd: Optional[float] = None
    net_amount_usdt: Optional[float] = None
    status: str
    seller_wallet_snapshot: Optional[str] = None
    admin_tx_hash: Optional[str] = None
    admin_tx_network: Optional[str] = None
    admin_tx_memo: Optional[str] = None
    admin_tx_confirmed_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    last_status_change_at: Optional[datetime] = None
    last_status_changed_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    line_items: List[PayoutLineItem] = Field(default_factory=list)
    events: List[PayoutEvent] = Field(default_factory=list)


class PayoutLedgerSummary(BaseModel):
    id: str
    period_start: datetime
    period_end: datetime
    settlement_due_at: datetime
    status: str
    gross_amount_usd: float
    net_amount_usdt: Optional[float] = None
    currency: str
    admin_tx_hash: Optional[str] = None
    admin_tx_confirmed_at: Optional[datetime] = None
    last_status_change_at: Optional[datetime] = None


class PayoutDashboardResponse(BaseModel):
    settings: Optional[PayoutSettings] = None
    next_settlement_at: Optional[datetime] = None
    pending_net_amount_usdt: float = 0
    pending_records: List[PayoutLedgerSummary] = Field(default_factory=list)
    recent_records: List[PayoutLedgerSummary] = Field(default_factory=list)


class AdminPayoutListFilters(BaseModel):
    status: Optional[str] = None
    seller_query: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


class AdminPayoutListItem(BaseModel):
    id: str
    seller_id: str
    seller_username: Optional[str] = None
    seller_email: Optional[str] = None
    status: str
    net_amount_usdt: Optional[float] = None
    gross_amount_usd: float
    settlement_due_at: datetime
    period_start: datetime
    period_end: datetime
    created_at: datetime
    updated_at: datetime


class AdminPayoutListResponse(BaseModel):
    total: int
    data: List[AdminPayoutListItem]


class AdminPayoutGenerateRequest(BaseModel):
    reference_date: Optional[datetime] = None
    lookback_days: int = Field(default=14, ge=1, le=60)
    fee_percent: float = Field(default=5.0, ge=0.0, le=25.0)
    min_net_threshold_usd: float = Field(default=5.0, ge=0.0)


class AdminPayoutStatusUpdateRequest(BaseModel):
    status: str
    note: Optional[str] = None


class AdminPayoutTxRecordRequest(BaseModel):
    tx_hash: str
    tx_network: Optional[str] = Field(default="TRC20")
    tx_memo: Optional[str] = None
    confirmed_at: Optional[datetime] = None


class AdminPayoutEventRequest(BaseModel):
    event_type: str = Field(default="note")
    title: Optional[str] = None
    body: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
