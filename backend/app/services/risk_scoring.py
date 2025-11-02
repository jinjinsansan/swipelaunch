from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.utils.dates import parse_iso_datetime


@dataclass
class RiskResult:
    score: float
    indicators: List[str]


def calculate_note_risk(
    note: Dict[str, Any],
    *,
    total_purchases: int = 0,
    suspicious_shares: int = 0,
    total_refunds: int = 0,
) -> RiskResult:
    score = 0.0
    indicators: List[str] = []

    if note.get("status") == "published":
        score += 20
        indicators.append("公開中")

    if note.get("is_paid"):
        score += 8
        indicators.append("有料販売")

    price_points = int(note.get("price_points") or 0)
    if price_points:
        if price_points >= 5000:
            score += 6
            indicators.append("高額ポイント")
        score += min(price_points / 1000.0, 6)

    price_jpy = note.get("price_jpy")
    if price_jpy is not None:
        price_value = int(price_jpy or 0)
        if price_value:
            if price_value >= 10000:
                score += 8
                indicators.append("高額JPY")
            score += min(price_value / 2000.0, 8)

    if total_purchases > 0:
        score += min(total_purchases * 2.5, 30)
        indicators.append(f"購入:{total_purchases}")

    if suspicious_shares > 0:
        score += 15 + min(suspicious_shares * 5, 25)
        indicators.append(f"疑いシェア:{suspicious_shares}")

    if total_refunds > 0:
        score += min(total_refunds * 6, 24)
        indicators.append(f"返金:{total_refunds}")

    updated_at = parse_iso_datetime(note.get("updated_at"))
    if updated_at:
        age_days = (datetime.now(timezone.utc) - updated_at).days
        if age_days <= 7:
            score += 5
            indicators.append("直近更新")

    return RiskResult(score=round(score, 1), indicators=indicators)


def calculate_salon_risk(
    salon: Dict[str, Any],
    *,
    active_members: int = 0,
    pending_members: int = 0,
    canceled_members: int = 0,
    monthly_price_jpy: Optional[int] = None,
    refunds: int = 0,
) -> RiskResult:
    score = 0.0
    indicators: List[str] = []

    status = salon.get("status") or ("active" if salon.get("is_active", True) else "suspended")
    if status in {"pending", "review"}:
        score += 25
        indicators.append("審査待ち")
    elif status in {"suspended", "halted"}:
        score += 30
        indicators.append("停止中")
    elif not salon.get("is_active", True):
        score += 15
        indicators.append("非アクティブ")

    if pending_members > 0:
        score += min(pending_members * 4.0, 20)
        indicators.append(f"審査中会員:{pending_members}")

    if canceled_members > 0:
        score += min(canceled_members * 3.0, 18)
        indicators.append(f"解約:{canceled_members}")

    if active_members > 0:
        score += min(active_members * 1.5, 18)
        indicators.append(f"会員:{active_members}")

    price = monthly_price_jpy if monthly_price_jpy is not None else salon.get("monthly_price_jpy")
    if price:
        price_int = int(price or 0)
        if price_int >= 20000:
            score += 8
            indicators.append("高額プラン")
        score += min(price_int / 4000.0, 10)

    if refunds > 0:
        score += min(refunds * 5.0, 20)
        indicators.append(f"返金:{refunds}")

    created_at = parse_iso_datetime(salon.get("created_at"))
    if created_at:
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days <= 14:
            score += 4
            indicators.append("新規開設")

    return RiskResult(score=round(score, 1), indicators=indicators)
