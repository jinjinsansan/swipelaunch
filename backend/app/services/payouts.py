from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from supabase import Client, create_client

from app.config import settings
from app.models.payouts import (
    AdminPayoutEventRequest,
    AdminPayoutGenerateRequest,
    AdminPayoutListFilters,
    AdminPayoutListItem,
    AdminPayoutListResponse,
    AdminRiskOrder,
    AdminRiskOrderListResponse,
    AdminPayoutStatusUpdateRequest,
    AdminPayoutTxRecordRequest,
    PayoutDashboardResponse,
    PayoutEvent,
    PayoutLedgerEntry,
    PayoutLedgerSummary,
    PayoutLineItem,
    PayoutSettings,
    PayoutSettingsUpsertRequest,
)
from app.services.platform_settings import get_platform_settings


logger = logging.getLogger(__name__)


PAYOUT_PENDING_STATUSES = {"pending", "funds_received", "ready_to_payout"}
DEFAULT_USD_TO_USDT = Decimal("1.0")  # Assume 1:1 peg


def _get_effective_exchange_rate_decimal(client: Optional[Client] = None) -> Decimal:
    platform_settings = get_platform_settings(client=client)
    effective_rate = Decimal(str(platform_settings.effective_exchange_rate))
    if effective_rate <= 0:
        fallback = Decimal(str(settings.default_exchange_rate_usd_jpy + settings.default_exchange_spread_jpy))
        if fallback <= 0:
            return Decimal("1")
        return fallback
    return effective_rate


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def _to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        candidate = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to parse datetime", extra={"value": value})
    return None


def _ensure_metadata(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to parse metadata JSON", extra={"value": value})
    return {}


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(item) for item in value]
    return value


def _map_settings(record: Optional[Dict[str, Any]]) -> Optional[PayoutSettings]:
    if not record:
        return None
    return PayoutSettings(
        user_id=str(record.get("user_id")),
        usdt_address=str(record.get("usdt_address")),
        address_label=record.get("address_label"),
        preferred_network=record.get("preferred_network") or "TRC20",
        payout_cycle_days=int(record.get("payout_cycle_days") or 10),
        address_verified_at=_to_datetime(record.get("address_verified_at")),
        payout_note=record.get("payout_note"),
        last_reviewed_at=_to_datetime(record.get("last_reviewed_at")),
        reviewer_id=record.get("reviewer_id"),
        created_at=_to_datetime(record.get("created_at")),
        updated_at=_to_datetime(record.get("updated_at")),
    )


def _map_line_item(record: Dict[str, Any]) -> PayoutLineItem:
    metadata = _ensure_metadata(record.get("metadata"))
    return PayoutLineItem(
        id=str(record.get("id")),
        payout_id=str(record.get("payout_id")),
        source_type=str(record.get("source_type")),
        source_id=str(record.get("source_id")),
        occurred_at=_to_datetime(record.get("occurred_at")),
        description=record.get("description"),
        gross_amount_usd=_to_decimal(record.get("gross_amount_usd")),
        gross_amount_jpy=_to_decimal(record.get("gross_amount_jpy")),
        gross_amount_points=record.get("gross_amount_points"),
        gross_amount_usdt=_to_decimal(record.get("gross_amount_usdt")),
        fee_amount_usd=_to_decimal(record.get("fee_amount_usd")),
        fee_amount_usdt=_to_decimal(record.get("fee_amount_usdt")),
        net_amount_usd=_to_decimal(record.get("net_amount_usd")),
        net_amount_usdt=_to_decimal(record.get("net_amount_usdt")),
        metadata=metadata,
        created_at=_to_datetime(record.get("created_at")),
        reserve_amount_usd=_to_decimal(record.get("reserve_amount_usd")),
    )


def _map_event(record: Dict[str, Any]) -> PayoutEvent:
    metadata = _ensure_metadata(record.get("metadata"))
    return PayoutEvent(
        id=str(record.get("id")),
        payout_id=str(record.get("payout_id")),
        event_type=str(record.get("event_type")),
        title=record.get("title"),
        body=record.get("body"),
        actor_id=record.get("actor_id"),
        metadata=metadata,
        created_at=_to_datetime(record.get("created_at")) or datetime.now(timezone.utc),
    )


def _map_ledger_summary(record: Dict[str, Any]) -> PayoutLedgerSummary:
    gross_amount_usd = _to_decimal(record.get("gross_amount_usd")) or Decimal("0")
    net_amount_usdt = _to_decimal(record.get("net_amount_usdt"))
    return PayoutLedgerSummary(
        id=str(record.get("id")),
        period_start=_to_datetime(record.get("period_start")) or datetime.now(timezone.utc),
        period_end=_to_datetime(record.get("period_end")) or datetime.now(timezone.utc),
        settlement_due_at=_to_datetime(record.get("settlement_due_at")) or datetime.now(timezone.utc),
        status=str(record.get("status")),
        gross_amount_usd=float(gross_amount_usd),
        net_amount_usdt=float(net_amount_usdt) if net_amount_usdt is not None else None,
        currency=str(record.get("currency")) if record.get("currency") else "USDT",
        admin_tx_hash=record.get("admin_tx_hash"),
        admin_tx_confirmed_at=_to_datetime(record.get("admin_tx_confirmed_at")),
        last_status_change_at=_to_datetime(record.get("last_status_change_at")),
    )


def _map_ledger_entry(record: Dict[str, Any], *, line_items: Iterable[PayoutLineItem], events: Iterable[PayoutEvent]) -> PayoutLedgerEntry:
    gross_amount_usd = _to_decimal(record.get("gross_amount_usd")) or Decimal("0")
    gross_amount_usdt = _to_decimal(record.get("gross_amount_usdt"))
    fee_amount_usd = _to_decimal(record.get("fee_amount_usd"))
    fee_amount_usdt = _to_decimal(record.get("fee_amount_usdt"))
    net_amount_usd = _to_decimal(record.get("net_amount_usd"))
    net_amount_usdt = _to_decimal(record.get("net_amount_usdt"))
    metadata = _ensure_metadata(record.get("metadata"))

    return PayoutLedgerEntry(
        id=str(record.get("id")),
        seller_id=str(record.get("seller_id")),
        seller_username=record.get("seller_username"),
        seller_email=record.get("seller_email"),
        period_start=_to_datetime(record.get("period_start")) or datetime.now(timezone.utc),
        period_end=_to_datetime(record.get("period_end")) or datetime.now(timezone.utc),
        settlement_due_at=_to_datetime(record.get("settlement_due_at")) or datetime.now(timezone.utc),
        funds_expected_at=_to_datetime(record.get("funds_expected_at")),
        payout_cycle_days=int(record.get("payout_cycle_days") or 10),
        one_lat_batch_id=record.get("one_lat_batch_id"),
        currency=str(record.get("currency")) if record.get("currency") else "USDT",
        gross_amount_usd=float(gross_amount_usd),
        gross_amount_usdt=float(gross_amount_usdt) if gross_amount_usdt is not None else None,
        gross_amount_points=record.get("gross_amount_points"),
        fee_amount_usd=float(fee_amount_usd) if fee_amount_usd is not None else None,
        fee_amount_usdt=float(fee_amount_usdt) if fee_amount_usdt is not None else None,
        net_amount_usd=float(net_amount_usd) if net_amount_usd is not None else None,
        net_amount_usdt=float(net_amount_usdt) if net_amount_usdt is not None else None,
        status=str(record.get("status")),
        seller_wallet_snapshot=record.get("seller_wallet_snapshot"),
        admin_tx_hash=record.get("admin_tx_hash"),
        admin_tx_network=record.get("admin_tx_network"),
        admin_tx_memo=record.get("admin_tx_memo"),
        admin_tx_confirmed_at=_to_datetime(record.get("admin_tx_confirmed_at")),
        notes=record.get("notes"),
        metadata=metadata,
        last_status_change_at=_to_datetime(record.get("last_status_change_at")),
        last_status_changed_by=record.get("last_status_changed_by"),
        created_at=_to_datetime(record.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_to_datetime(record.get("updated_at")) or datetime.now(timezone.utc),
        line_items=list(line_items),
        events=list(events),
    )


def get_payout_settings(user_id: str, *, supabase: Optional[Client] = None) -> Optional[PayoutSettings]:
    client = supabase or get_supabase()
    response = (
        client
        .table("payout_settings")
        .select("*")
        .eq("user_id", user_id)
        .range(0, 0)
        .execute()
    )
    record = (response.data or [None])[0]
    return _map_settings(record)


def upsert_payout_settings(user_id: str, payload: PayoutSettingsUpsertRequest, *, actor_id: Optional[str] = None, supabase: Optional[Client] = None) -> PayoutSettings:
    client = supabase or get_supabase()
    data = {
        "user_id": user_id,
        "usdt_address": payload.usdt_address,
        "address_label": payload.address_label,
        "preferred_network": payload.preferred_network or "TRC20",
        "payout_note": payload.payout_note,
        "reviewer_id": actor_id,
        "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    response = client.table("payout_settings").upsert(data, on_conflict="user_id").execute()
    record = (response.data or [None])[0]
    return _map_settings(record)  # type: ignore[arg-type]


def get_payout_dashboard(user_id: str, *, supabase: Optional[Client] = None) -> PayoutDashboardResponse:
    client = supabase or get_supabase()
    settings = get_payout_settings(user_id, supabase=client)

    ledger_resp = (
        client
        .table("payout_ledger")
        .select("*")
        .eq("seller_id", user_id)
        .order("settlement_due_at", desc=False)
        .execute()
    )
    rows = ledger_resp.data or []

    pending: List[PayoutLedgerSummary] = []
    recent: List[PayoutLedgerSummary] = []
    pending_total = Decimal("0")
    next_settlement_at: Optional[datetime] = None

    for row in rows:
        summary = _map_ledger_summary(row)
        if summary.status in PAYOUT_PENDING_STATUSES:
            pending.append(summary)
            net_amount = summary.net_amount_usdt
            if net_amount is None:
                net_amount = summary.gross_amount_usd
            if net_amount is not None:
                pending_total += Decimal(str(net_amount))
            candidate_due = summary.settlement_due_at
            if candidate_due and (not next_settlement_at or candidate_due < next_settlement_at):
                next_settlement_at = candidate_due
        else:
            recent.append(summary)

    recent.sort(key=lambda item: item.settlement_due_at, reverse=True)
    recent = recent[:10]

    return PayoutDashboardResponse(
        settings=settings,
        next_settlement_at=next_settlement_at,
        pending_net_amount_usdt=float(pending_total),
        pending_records=pending,
        recent_records=recent,
    )


def get_payout_detail(payout_id: str, *, supabase: Optional[Client] = None) -> Optional[PayoutLedgerEntry]:
    client = supabase or get_supabase()
    ledger_resp = (
        client
        .table("payout_ledger")
        .select("*")
        .eq("id", payout_id)
        .range(0, 0)
        .execute()
    )
    record = (ledger_resp.data or [None])[0]
    if not record:
        return None

    items_resp = (
        client
        .table("payout_line_items")
        .select("*")
        .eq("payout_id", payout_id)
        .order("occurred_at", desc=False)
        .execute()
    )
    events_resp = (
        client
        .table("payout_events")
        .select("*")
        .eq("payout_id", payout_id)
        .order("created_at", desc=False)
        .execute()
    )

    items = [_map_line_item(row) for row in (items_resp.data or [])]
    events = [_map_event(row) for row in (events_resp.data or [])]

    return _map_ledger_entry(record, line_items=items, events=events)


def list_admin_payouts(filters: AdminPayoutListFilters, *, limit: int = 50, offset: int = 0, supabase: Optional[Client] = None) -> AdminPayoutListResponse:
    client = supabase or get_supabase()
    query = (
        client
        .table("payout_ledger")
        .select("*")
        .order("settlement_due_at", desc=False)
    )

    if filters.status:
        query = query.eq("status", filters.status)

    response = query.execute()
    rows = response.data or []

    filtered: List[Dict[str, Any]] = []
    for row in rows:
        include = True
        if filters.seller_query:
            seller_query_lower = filters.seller_query.lower()
            seller_name = str(row.get("seller_username") or "").lower()
            seller_email = str(row.get("seller_email") or "").lower()
            seller_id = str(row.get("seller_id") or "").lower()
            include = any(
                seller_query_lower in candidate
                for candidate in (seller_name, seller_email, seller_id)
                if candidate
            )
        if include and filters.from_date:
            due_at = _to_datetime(row.get("settlement_due_at"))
            if due_at and due_at < filters.from_date:
                include = False
        if include and filters.to_date:
            due_at = _to_datetime(row.get("settlement_due_at"))
            if due_at and due_at > filters.to_date:
                include = False
        if include:
            filtered.append(row)

    total = len(filtered)
    paged = filtered[offset : offset + limit]

    items: List[AdminPayoutListItem] = []
    for row in paged:
        gross_amount_usd = float(_to_decimal(row.get("gross_amount_usd")) or Decimal("0"))
        net_amount_usdt = _to_decimal(row.get("net_amount_usdt"))
        items.append(
            AdminPayoutListItem(
                id=str(row.get("id")),
                seller_id=str(row.get("seller_id")),
                seller_username=row.get("seller_username"),
                seller_email=row.get("seller_email"),
                status=str(row.get("status")),
                net_amount_usdt=float(net_amount_usdt) if net_amount_usdt is not None else None,
                gross_amount_usd=gross_amount_usd,
                settlement_due_at=_to_datetime(row.get("settlement_due_at")) or datetime.now(timezone.utc),
                period_start=_to_datetime(row.get("period_start")) or datetime.now(timezone.utc),
                period_end=_to_datetime(row.get("period_end")) or datetime.now(timezone.utc),
                created_at=_to_datetime(row.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_to_datetime(row.get("updated_at")) or datetime.now(timezone.utc),
            )
        )

    return AdminPayoutListResponse(total=total, data=items)


def list_risk_orders(*, limit: int = 50, supabase: Optional[Client] = None) -> AdminRiskOrderListResponse:
    client = supabase or get_supabase()
    orders_resp = (
        client
        .table("payment_orders")
        .select("*")
        .eq("status", "COMPLETED")
        .order("completed_at", desc=True)
        .execute()
    )
    rows = orders_resp.data or []
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        clearing_state = str(row.get("clearing_state") or "").lower()
        risk_level = str(row.get("risk_level") or "").lower()
        dispute_flag = bool(row.get("dispute_flag"))
        if clearing_state in {"clearing", "dispute"} or dispute_flag or risk_level == "high":
            filtered.append(row)
        if len(filtered) >= limit:
            break

    seller_ids = {row.get("seller_id") for row in filtered if row.get("seller_id")}
    seller_lookup = _load_sellers(client, seller_ids)
    buyer_ids = {row.get("user_id") for row in filtered if row.get("user_id")}
    buyer_lookup: Dict[str, Dict[str, Any]] = {}
    if buyer_ids:
        buyers_resp = (
            client
            .table("users")
            .select("id, username, email")
            .in_("id", list(buyer_ids))
            .execute()
        )
        for record in buyers_resp.data or []:
            user_id = record.get("id")
            if user_id:
                buyer_lookup[str(user_id)] = record

    items: List[AdminRiskOrder] = []
    for row in filtered:
        seller_id = str(row.get("seller_id")) if row.get("seller_id") else ""
        metadata = _ensure_metadata(row.get("metadata"))
        risk_score = row.get("risk_score")
        item = AdminRiskOrder(
            order_id=str(row.get("id")),
            seller_id=seller_id,
            seller_username=seller_lookup.get(seller_id, {}).get("username"),
            seller_email=seller_lookup.get(seller_id, {}).get("email"),
            buyer_id=row.get("user_id"),
            buyer_username=buyer_lookup.get(str(row.get("user_id")), {}).get("username"),
            amount_jpy=int(row.get("amount_jpy") or 0),
            currency=str(row.get("currency") or "JPY"),
            risk_level=row.get("risk_level"),
            risk_score=int(risk_score) if risk_score is not None else None,
            clearing_state=row.get("clearing_state"),
            dispute_flag=bool(row.get("dispute_flag")),
            dispute_status=row.get("dispute_status"),
            ready_for_payout_at=_to_datetime(row.get("ready_for_payout_at")) if row.get("ready_for_payout_at") else None,
            chargeback_hold_until=_to_datetime(row.get("chargeback_hold_until")) if row.get("chargeback_hold_until") else None,
            reserve_amount_usd=float(row.get("reserve_amount_usd")) if row.get("reserve_amount_usd") is not None else None,
            created_at=_to_datetime(row.get("created_at")) if row.get("created_at") else datetime.now(timezone.utc),
            completed_at=_to_datetime(row.get("completed_at")) if row.get("completed_at") else None,
            metadata=metadata,
        )
        items.append(item)

    return AdminRiskOrderListResponse(total=len(filtered), data=items)


def create_admin_event(payout_id: str, request: AdminPayoutEventRequest, *, actor_id: Optional[str], supabase: Optional[Client] = None) -> PayoutEvent:
    client = supabase or get_supabase()
    payload = {
        "payout_id": payout_id,
        "event_type": request.event_type,
        "title": request.title or request.event_type.title(),
        "body": request.body,
        "actor_id": actor_id,
        "metadata": request.metadata,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    response = client.table("payout_events").insert(payload).execute()
    record = (response.data or [payload])[0]
    return _map_event(record)


def update_payout_status(payout_id: str, request: AdminPayoutStatusUpdateRequest, *, actor_id: Optional[str], supabase: Optional[Client] = None) -> Optional[PayoutLedgerEntry]:
    client = supabase or get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    update_payload = {
        "status": request.status,
        "last_status_change_at": now,
        "last_status_changed_by": actor_id,
    }
    if request.note:
        update_payload["notes"] = request.note

    client.table("payout_ledger").update(update_payload).eq("id", payout_id).execute()

    event_body = request.note or f"Status changed to {request.status}"
    event = AdminPayoutEventRequest(
        event_type="status_change",
        title=f"Status → {request.status}",
        body=event_body,
        metadata={"status": request.status},
    )
    create_admin_event(payout_id, event, actor_id=actor_id, supabase=client)
    return get_payout_detail(payout_id, supabase=client)


def record_admin_transaction(payout_id: str, request: AdminPayoutTxRecordRequest, *, actor_id: Optional[str], supabase: Optional[Client] = None) -> Optional[PayoutLedgerEntry]:
    client = supabase or get_supabase()
    confirmed_at = request.confirmed_at or datetime.now(timezone.utc)
    update_payload = {
        "admin_tx_hash": request.tx_hash,
        "admin_tx_network": request.tx_network or "TRC20",
        "admin_tx_memo": request.tx_memo,
        "admin_tx_confirmed_at": confirmed_at.isoformat(),
    }
    client.table("payout_ledger").update(update_payload).eq("id", payout_id).execute()
    orders_resp = (
        client
        .table("payout_line_items")
        .select("source_id, source_type")
        .eq("payout_id", payout_id)
        .eq("source_type", "payment_order")
        .execute()
    )
    order_ids = [row.get("source_id") for row in (orders_resp.data or []) if row.get("source_id")]
    if order_ids:
        client.table("payment_orders").update(
            {
                "reserve_released_at": confirmed_at.isoformat(),
                "clearing_state": "released",
            }
        ).in_("id", order_ids).execute()

    event = AdminPayoutEventRequest(
        event_type="transaction",
        title="送金完了を記録",
        body=f"Tx Hash: {request.tx_hash}",
        metadata={
            "tx_hash": request.tx_hash,
            "tx_network": request.tx_network or "TRC20",
            "tx_memo": request.tx_memo,
        },
    )
    create_admin_event(payout_id, event, actor_id=actor_id, supabase=client)
    return get_payout_detail(payout_id, supabase=client)


def _load_sellers(client: Client, seller_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = list({sid for sid in seller_ids if sid})
    if not ids:
        return {}
    response = client.table("users").select("id, username, email").in_("id", ids).execute()
    mapping: Dict[str, Dict[str, Any]] = {}
    for row in response.data or []:
        sid = row.get("id")
        if sid:
            mapping[str(sid)] = row
    return mapping


def _load_settings_map(client: Client, seller_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = list({sid for sid in seller_ids if sid})
    if not ids:
        return {}
    response = client.table("payout_settings").select("*").in_("user_id", ids).execute()
    mapping: Dict[str, Dict[str, Any]] = {}
    for row in response.data or []:
        uid = row.get("user_id")
        if uid:
            mapping[str(uid)] = row
    return mapping


def generate_payouts(request: AdminPayoutGenerateRequest, *, actor_id: Optional[str], supabase: Optional[Client] = None) -> Dict[str, Any]:
    client = supabase or get_supabase()
    reference_date = request.reference_date or datetime.now(timezone.utc)
    window_start = reference_date - timedelta(days=request.lookback_days)

    logger.info(
        "Generating payout ledger entries",
        extra={
            "reference_date": reference_date.isoformat(),
            "window_start": window_start.isoformat(),
            "fee_percent": request.fee_percent,
        },
    )

    # Load assigned payment order ids to avoid duplicates
    existing_resp = (
        client
        .table("payout_line_items")
        .select("source_id")
        .eq("source_type", "payment_order")
        .execute()
    )
    assigned_ids = {row.get("source_id") for row in (existing_resp.data or []) if row.get("source_id")}

    orders_resp = (
        client
        .table("payment_orders")
        .select(
            "id, seller_id, user_id, amount_jpy, currency, metadata, completed_at, status, "
            "clearing_state, ready_for_payout_at, chargeback_hold_until, dispute_flag, risk_level, risk_score, reserve_amount_usd"
        )
        .eq("status", "COMPLETED")
        .order("completed_at", desc=False)
        .execute()
    )

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in orders_resp.data or []:
        order_id = row.get("id")
        seller_id = row.get("seller_id")
        completed_at = _to_datetime(row.get("completed_at"))
        if not order_id or not seller_id or not completed_at:
            continue
        if order_id in assigned_ids:
            continue
        if completed_at < window_start:
            continue
        if row.get("dispute_flag"):
            continue
        clearing_state = (row.get("clearing_state") or "").lower()
        ready_at = _to_datetime(row.get("ready_for_payout_at")) if row.get("ready_for_payout_at") else None
        if not ready_at:
            hold_reference = _to_datetime(row.get("chargeback_hold_until")) if row.get("chargeback_hold_until") else None
            ready_at = hold_reference or (completed_at + timedelta(days=10))
        if clearing_state == "dispute":
            continue
        if ready_at > reference_date:
            continue
        grouped[str(seller_id)].append(row)

    if not grouped:
        return {"created": [], "total_created": 0}

    seller_lookup = _load_sellers(client, grouped.keys())
    settings_lookup = _load_settings_map(client, grouped.keys())

    created_entries: List[str] = []

    fee_ratio = Decimal(str(request.fee_percent)) / Decimal("100")
    exchange_rate_decimal = _get_effective_exchange_rate_decimal(client)

    for seller_id, orders in grouped.items():
        period_start: Optional[datetime] = None
        period_end: Optional[datetime] = None
        gross_usd_total = Decimal("0")
        line_items_payload: List[Dict[str, Any]] = []
        reserve_total_usd = Decimal("0")

        order_ids: List[str] = []
        for order in orders:
            completed_at = _to_datetime(order.get("completed_at")) or reference_date
            if not period_start or completed_at < period_start:
                period_start = completed_at
            if not period_end or completed_at > period_end:
                period_end = completed_at

            metadata = _ensure_metadata(order.get("metadata"))
            amount_usd = _to_decimal(order.get("amount_usd"))
            if amount_usd is None:
                meta_usd = metadata.get("amount_usd")
                amount_usd = _to_decimal(meta_usd)
            if amount_usd is None:
                amount_jpy = _to_decimal(order.get("amount_jpy")) or Decimal("0")
                amount_usd = amount_jpy / exchange_rate_decimal if amount_jpy else Decimal("0")

            gross_usd_total += amount_usd or Decimal("0")
            fee_usd = (amount_usd or Decimal("0")) * fee_ratio
            net_usd = (amount_usd or Decimal("0")) - fee_usd

            reserve_usd = _to_decimal(order.get("reserve_amount_usd")) if order.get("reserve_amount_usd") is not None else Decimal("0")
            reserve_total_usd += reserve_usd
            if order.get("id"):
                order_ids.append(str(order.get("id")))
            line_items_payload.append(
                {
                    "source_type": "payment_order",
                    "source_id": order.get("id"),
                    "seller_id": seller_id,
                    "occurred_at": completed_at.isoformat(),
                    "buyer_id": order.get("user_id"),
                    "description": metadata.get("description"),
                    "gross_amount_usd": float(amount_usd),
                    "gross_amount_jpy": order.get("amount_jpy"),
                    "gross_amount_usdt": float(amount_usd * DEFAULT_USD_TO_USDT),
                    "fee_amount_usd": float(fee_usd),
                    "fee_amount_usdt": float(fee_usd * DEFAULT_USD_TO_USDT),
                    "net_amount_usd": float(net_usd),
                    "net_amount_usdt": float(net_usd * DEFAULT_USD_TO_USDT),
                    "metadata": {
                        "currency": order.get("currency", "USD"),
                        "raw_metadata": _sanitize_for_json(metadata),
                        "risk_level": order.get("risk_level"),
                        "risk_score": order.get("risk_score"),
                    },
                    "reserve_amount_usd": float(reserve_usd) if reserve_usd else 0,
                }
            )

        if gross_usd_total <= Decimal("0"):
            continue

        fee_total = gross_usd_total * fee_ratio
        net_usd_total = gross_usd_total - fee_total
        if reserve_total_usd > Decimal("0"):
            net_usd_total = max(net_usd_total - reserve_total_usd, Decimal("0"))
        if net_usd_total < Decimal(str(request.min_net_threshold_usd)):
            logger.info(
                "Skipping payout below threshold",
                extra={"seller_id": seller_id, "net_usd": float(net_usd_total)},
            )
            continue

        seller_info = seller_lookup.get(seller_id, {})
        settings_record = settings_lookup.get(seller_id, {})
        wallet_snapshot = settings_record.get("usdt_address")

        ledger_payload = {
            "seller_id": seller_id,
            "seller_username": seller_info.get("username"),
            "seller_email": seller_info.get("email"),
            "period_start": (period_start or reference_date).isoformat(),
            "period_end": (period_end or reference_date).isoformat(),
            "settlement_due_at": ((period_end or reference_date) + timedelta(days=10)).isoformat(),
            "funds_expected_at": (reference_date + timedelta(days=3)).isoformat(),
            "payout_cycle_days": int(settings_record.get("payout_cycle_days") or 10),
            "currency": "USDT",
            "gross_amount_usd": float(gross_usd_total),
            "gross_amount_usdt": float(gross_usd_total * DEFAULT_USD_TO_USDT),
            "fee_amount_usd": float(fee_total),
            "fee_amount_usdt": float(fee_total * DEFAULT_USD_TO_USDT),
            "net_amount_usd": float(net_usd_total),
            "net_amount_usdt": float(net_usd_total * DEFAULT_USD_TO_USDT),
            "status": "ready_to_payout",
            "seller_wallet_snapshot": wallet_snapshot,
            "metadata": {
                "generated_by": actor_id,
                "generated_at": reference_date.isoformat(),
                "order_count": len(orders),
                "fee_percent": request.fee_percent,
                "reserve_withheld_usd": float(reserve_total_usd) if reserve_total_usd else 0,
            },
            "last_status_change_at": reference_date.isoformat(),
            "last_status_changed_by": actor_id,
        }

        ledger_resp = client.table("payout_ledger").insert(_sanitize_for_json(ledger_payload)).execute()
        ledger_record = (ledger_resp.data or [None])[0]
        payout_id = ledger_record.get("id") if ledger_record else None
        if not payout_id:
            logger.warning("Failed to insert payout ledger", extra={"seller_id": seller_id})
            continue

        for item in line_items_payload:
            item["payout_id"] = payout_id
        client.table("payout_line_items").insert([_sanitize_for_json(item) for item in line_items_payload]).execute()
        if order_ids:
            client.table("payment_orders").update(
                {
                    "clearing_state": "ready",
                    "risk_reviewed_at": reference_date.isoformat(),
                }
            ).in_("id", order_ids).execute()

        create_admin_event(
            payout_id,
            AdminPayoutEventRequest(
                event_type="generated",
                title="自動生成",
                body=f"{len(line_items_payload)}件の決済を取り込みました",
                metadata={"order_count": len(line_items_payload)},
            ),
            actor_id=actor_id,
            supabase=client,
        )

        created_entries.append(str(payout_id))

    return {"created": created_entries, "total_created": len(created_entries)}
