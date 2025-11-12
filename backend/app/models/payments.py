from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class BillingProfileMissingError(RuntimeError):
    """Raised when quick checkout requires billing profile."""


class QuickCheckoutRequest(BaseModel):
    item_type: Literal["note", "product", "subscription"]
    item_id: Optional[str] = Field(None, description="Target item identifier")
    plan_key: Optional[str] = Field(None, description="Subscription plan key (for subscription type)")
    quantity: Optional[int] = Field(1, ge=1, description="Product quantity (product type only)")
    locale: Optional[str] = Field(None, min_length=2, max_length=5, description="Preferred locale")
    seller_id: Optional[str] = Field(None, description="Seller identifier for attribution")
    seller_username: Optional[str] = Field(None, description="Seller username for redirect context")
    salon_id: Optional[str] = Field(None, description="Linked salon identifier")
    success_path: Optional[str] = Field(None, description="Custom success redirect path")
    error_path: Optional[str] = Field(None, description="Custom error redirect path")

    @model_validator(mode="after")
    def _validate_requirements(self) -> "QuickCheckoutRequest":
        if self.item_type in {"note", "product"} and not self.item_id:
            raise ValueError("item_id is required for note and product quick checkout")
        if self.item_type == "subscription" and not self.plan_key:
            raise ValueError("plan_key is required for subscription quick checkout")
        return self


class QuickCheckoutResponse(BaseModel):
    checkout_url: str
    external_id: str
    item_type: Literal["note", "product", "subscription"]
