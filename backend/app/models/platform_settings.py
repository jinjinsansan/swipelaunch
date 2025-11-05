from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator


class PlatformPaymentSettings(BaseModel):
    exchange_rate_usd_jpy: float = Field(..., gt=0, description="実勢のUSD/JPYレート")
    spread_jpy: float = Field(..., ge=0, description="運営が上乗せするスプレッド（円）")
    platform_fee_percent: float = Field(..., ge=0, description="決済手数料（%）")
    updated_at: Optional[datetime] = Field(None, description="最終更新日時")
    updated_by: Optional[str] = Field(None, description="更新したユーザーID")

    @property
    def effective_exchange_rate(self) -> float:
        """スプレッド込みの実効レートを返す"""
        return self.exchange_rate_usd_jpy + self.spread_jpy


class PlatformPaymentSettingsUpdateRequest(BaseModel):
    exchange_rate_usd_jpy: float = Field(..., gt=0, description="実勢のUSD/JPYレート")
    spread_jpy: float = Field(..., ge=0, le=50, description="上乗せするスプレッド（円）")
    platform_fee_percent: float = Field(..., ge=0, le=30, description="決済手数料（%）")

    @validator("exchange_rate_usd_jpy", "spread_jpy", "platform_fee_percent")
    def normalize_decimal(cls, value: float) -> float:
        return round(float(value), 4)
