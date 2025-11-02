from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict

from supabase import Client

DEFAULT_JPY_TO_USD = Decimal("145")


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:  # pragma: no cover - defensive
            return Decimal("0")
    return Decimal("0")


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _count_recent_orders(client: Client, user_id: str, completed_at: datetime) -> Dict[str, int]:
    window_start = completed_at - timedelta(hours=1)
    total_resp = (
        client
        .table("payment_orders")
        .select("id, completed_at")
        .eq("user_id", user_id)
        .eq("status", "COMPLETED")
        .lt("completed_at", completed_at.isoformat())
        .execute()
    )
    rows = total_resp.data or []
    total_completed = len(rows)
    recent_count = sum(
        1
        for row in rows
        if row.get("completed_at") and _to_datetime(row.get("completed_at")) >= window_start
    )
    return {"total_completed": total_completed, "recent_within_hour": recent_count}


def _determine_risk_level(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def evaluate_payment_order_risk(client: Client, order_row: Dict[str, Any]) -> Dict[str, Any]:
    amount_jpy = _to_decimal(order_row.get("amount_jpy"))
    amount_usd = _to_decimal(order_row.get("amount_usd")) if order_row.get("amount_usd") is not None else Decimal("0")
    if amount_jpy == 0 and amount_usd > 0:
        amount_jpy = amount_usd * DEFAULT_JPY_TO_USD
    currency = order_row.get("currency") or "JPY"
    metadata = order_row.get("metadata") or {}
    completed_at = _to_datetime(order_row.get("completed_at") or datetime.now(timezone.utc))
    user_id = order_row.get("user_id")

    score = 0
    factors: Dict[str, Any] = {}

    if amount_jpy >= Decimal("30000"):
        score += 3
        factors["high_amount"] = True
    elif amount_jpy >= Decimal("15000"):
        score += 2
        factors["mid_amount"] = True

    if currency and currency.upper() != "JPY":
        score += 1
        factors["non_jpy_currency"] = currency

    stats = {"total_completed": 0, "recent_within_hour": 0}
    if user_id:
        stats = _count_recent_orders(client, user_id, completed_at)
        if stats["total_completed"] == 0:
            score += 2
            factors["first_purchase"] = True
        if stats["recent_within_hour"] >= 2:
            score += 2
            factors["rapid_purchases"] = stats["recent_within_hour"]

    if metadata.get("suspected_fraud"):
        score += 3
        factors["suspected_fraud"] = True

    risk_level = _determine_risk_level(score)

    hold_days = 10
    reserve_percent = Decimal("0")
    if risk_level == "medium":
        hold_days = 21
        reserve_percent = Decimal("0.05")
    elif risk_level == "high":
        hold_days = 45
        reserve_percent = Decimal("0.10")

    ready_for_payout_at = completed_at + timedelta(days=hold_days)
    base_amount_usd = amount_usd if amount_usd > 0 else (amount_jpy / DEFAULT_JPY_TO_USD)
    reserve_amount_usd = (base_amount_usd * reserve_percent) if reserve_percent > 0 else Decimal("0")

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "risk_factors": factors,
        "chargeback_hold_until": ready_for_payout_at,
        "ready_for_payout_at": ready_for_payout_at,
        "clearing_state": "clearing",
        "reserve_amount_usd": float(reserve_amount_usd) if reserve_amount_usd else 0,
    }
