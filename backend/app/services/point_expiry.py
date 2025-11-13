"""Utilities for enforcing point expiration windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

POINT_EXPIRY_DAYS = 180


def _parse_timestamp(value: Any) -> datetime:
    """Parse timestamps returned by Supabase into timezone-aware UTC datetimes."""

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    return datetime.now(timezone.utc)


def _build_remaining_lots(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build FIFO lots representing unspent point amounts."""

    lots: List[Dict[str, Any]] = []

    for tx in sorted(transactions, key=lambda item: _parse_timestamp(item.get("created_at"))):
        amount = int(tx.get("amount") or 0)
        created_at = _parse_timestamp(tx.get("created_at"))

        if amount > 0:
            lots.append({
                "remaining": amount,
                "created_at": created_at,
                "transaction_type": tx.get("transaction_type"),
                "transaction_id": tx.get("id"),
            })
            continue

        if amount < 0:
            to_consume = -amount
            while to_consume > 0 and lots:
                current = lots[0]
                remaining = int(current.get("remaining", 0))
                if remaining <= 0:
                    lots.pop(0)
                    continue

                if remaining > to_consume:
                    current["remaining"] = remaining - to_consume
                    to_consume = 0
                else:
                    to_consume -= remaining
                    lots.pop(0)

    return [lot for lot in lots if int(lot.get("remaining", 0)) > 0]


def calculate_point_summary(
    transactions: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Calculate available and expired balances from raw transaction rows."""

    reference_time = now or datetime.now(timezone.utc)
    lots = _build_remaining_lots(transactions)

    total_remaining = sum(int(lot.get("remaining", 0)) for lot in lots)

    expiry_limit = reference_time - timedelta(days=POINT_EXPIRY_DAYS)
    expired_remaining = sum(
        int(lot.get("remaining", 0))
        for lot in lots
        if _parse_timestamp(lot.get("created_at")) <= expiry_limit
    )

    available_remaining = max(total_remaining - expired_remaining, 0)

    return {
        "available_balance": available_remaining,
        "expired_balance": expired_remaining,
        "tracked_balance": total_remaining,
    }


def sync_user_point_balance(
    supabase: Client,
    user_id: str,
    *,
    current_balance: Optional[int] = None,
) -> Dict[str, int]:
    """Ensure the stored user point balance excludes expired portions.

    Returns a summary dictionary containing the available and expired balances.
    """

    transactions_response = (
        supabase
        .table("point_transactions")
        .select("id, transaction_type, amount, created_at")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )

    transactions = transactions_response.data or []
    summary = calculate_point_summary(transactions)

    available_balance = summary["available_balance"]

    if current_balance is None:
        user_response = supabase.table("users").select("point_balance").eq("id", user_id).single().execute()
        if user_response.data:
            current_balance = int(user_response.data.get("point_balance", 0) or 0)
        else:
            current_balance = 0

    if available_balance != current_balance:
        supabase.table("users").update({"point_balance": available_balance}).eq("id", user_id).execute()

    summary["stored_balance"] = current_balance
    summary["point_balance"] = available_balance
    return summary
