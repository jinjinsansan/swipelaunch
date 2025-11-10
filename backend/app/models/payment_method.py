from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PaymentMethodBrand(BaseModel):
    label: str
    code: Optional[str] = None


class PaymentMethodSummary(BaseModel):
    id: str
    brand: Optional[str] = None
    brand_label: Optional[str] = None
    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
    revoked_at: Optional[datetime] = None


class PaymentMethodListResponse(BaseModel):
    items: List[PaymentMethodSummary] = Field(default_factory=list)


class InitiatePaymentMethodResponse(BaseModel):
    checkout_url: str = Field(..., description="OneLat hosted checkout URL to capture card details")
    checkout_preference_id: str = Field(..., description="Identifier for the OneLat checkout preference")
    external_id: str = Field(..., description="External identifier used to track the setup flow")


class ConfirmPaymentMethodRequest(BaseModel):
    checkout_preference_id: str = Field(..., description="The OneLat checkout preference ID used during setup")
    external_id: str = Field(..., description="The external identifier provided when initiating setup")


class SetDefaultPaymentMethodRequest(BaseModel):
    is_default: bool = Field(True, description="Whether this payment method should become the default")


class SavePaymentMethodRequest(BaseModel):
    payment_method_id: str = Field(..., description="Internal payment method record ID")
