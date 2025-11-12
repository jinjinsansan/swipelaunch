from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator, model_validator


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class BillingProfilePayload(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    postal_code: Optional[str] = None
    prefecture: Optional[str] = None
    city: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    company_name: Optional[str] = None
    country_code: Optional[str] = "JP"

    @field_validator(
        "full_name",
        "phone_number",
        "postal_code",
        "prefecture",
        "city",
        "address_line1",
        "address_line2",
        "company_name",
        "country_code",
        mode="before",
    )
    @classmethod
    def _trim_optional(cls, value: Optional[str]) -> Optional[str]:
        return _normalize(value)

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalize_country(cls, value: Optional[str]) -> Optional[str]:
        normalized = _normalize(value)
        if not normalized:
            return None
        return normalized.upper()

    @model_validator(mode="after")
    def _ensure_minimum_fields(self) -> "BillingProfilePayload":
        if not self.full_name:
            raise ValueError("full_name is required")
        if not self.email:
            raise ValueError("email is required")
        return self


class BillingProfileResponse(BaseModel):
    user_id: str
    profile: Optional[BillingProfilePayload] = None
    updated_at: Optional[datetime] = None


class BillingProfileRecord(BillingProfilePayload):
    created_at: datetime
    updated_at: datetime
