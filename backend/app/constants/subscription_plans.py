"""Subscription plan definitions shared across the backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.config import settings


@dataclass(frozen=True)
class SubscriptionPlan:
    """Represents a single recurring purchase plan."""

    key: str
    points: int
    usd_amount: float
    subscription_plan_id: str
    label: str


def _build_plan(key: str, points: int, usd_amount: float, plan_id: str) -> SubscriptionPlan:
    if not plan_id:
        raise ValueError(f"ONE.lat subscription plan ID is not configured for key '{key}'.")
    label = f"{points:,}pt / 月"
    return SubscriptionPlan(
        key=key,
        points=points,
        usd_amount=usd_amount,
        subscription_plan_id=plan_id,
        label=label,
    )


SUBSCRIPTION_PLANS: List[SubscriptionPlan] = [
    _build_plan("points_980", 980, 6.76, settings.one_lat_plan_980_id),
    _build_plan("points_1980", 1980, 13.66, settings.one_lat_plan_1980_id),
    _build_plan("points_2980", 2980, 20.55, settings.one_lat_plan_2980_id),
    _build_plan("points_4980", 4980, 34.34, settings.one_lat_plan_4980_id),
    _build_plan("points_9980", 9980, 68.83, settings.one_lat_plan_9980_id),
]

SUBSCRIPTION_PLAN_MAP: Dict[str, SubscriptionPlan] = {plan.key: plan for plan in SUBSCRIPTION_PLANS}
SUBSCRIPTION_PLAN_ID_MAP: Dict[str, SubscriptionPlan] = {
    plan.subscription_plan_id: plan for plan in SUBSCRIPTION_PLANS
}


def get_subscription_plan(plan_key: str) -> Optional[SubscriptionPlan]:
    """Retrieve a subscription plan by its key."""

    return SUBSCRIPTION_PLAN_MAP.get(plan_key)


def get_subscription_plan_by_id(subscription_plan_id: str) -> Optional[SubscriptionPlan]:
    """Retrieve a subscription plan by ONE.lat subscription ID."""

    return SUBSCRIPTION_PLAN_ID_MAP.get(subscription_plan_id)
