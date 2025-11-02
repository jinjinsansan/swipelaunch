from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from supabase import Client, create_client

from app.config import settings
from app.models.payouts import (
    AdminPayoutEventRequest,
    AdminPayoutGenerateRequest,
    AdminPayoutListFilters,
    AdminPayoutListItem,
    AdminPayoutListResponse,
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


logger = logging.getLogger(__name__)


PAYOUT_PENDING_STATUSES = {"pending", "funds_received", "ready_to_payout"}
DEFAULT_POINT_EXCHANGE_RATE = Decimal("145.0")  # 1 USD = 145pt
DEFAULT_USD_TO_USDT = Decimal("1.0")  # Assume 1:1 peg


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
        .select("id, seller_id, user_id, amount_jpy, currency, amount_usd, metadata, completed_at, status")
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
        payout_ready_at = completed_at + timedelta(days=10)
        if payout_ready_at > reference_date:
            continue
        grouped[str(seller_id)].append(row)

    if not grouped:
        return {"created": [], "total_created": 0}

    seller_lookup = _load_sellers(client, grouped.keys())
    settings_lookup = _load_settings_map(client, grouped.keys())

    created_entries: List[str] = []

    fee_ratio = Decimal(str(request.fee_percent)) / Decimal("100")

    for seller_id, orders in grouped.items():
        period_start: Optional[datetime] = None
        period_end: Optional[datetime] = None
        gross_usd_total = Decimal("0")
        line_items_payload: List[Dict[str, Any]] = []

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
                amount_usd = amount_jpy / DEFAULT_POINT_EXCHANGE_RATE

            gross_usd_total += amount_usd or Decimal("0")
            fee_usd = (amount_usd or Decimal("0")) * fee_ratio
            net_usd = (amount_usd or Decimal("0")) - fee_usd

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
                        "raw_metadata": metadata,
                    },
                }
            )

        if gross_usd_total <= Decimal("0"):
            continue

        fee_total = gross_usd_total * fee_ratio
        net_usd_total = gross_usd_total - fee_total
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
            },
            "last_status_change_at": reference_date.isoformat(),
            "last_status_changed_by": actor_id,
        }

        ledger_resp = client.table("payout_ledger").insert(ledger_payload).execute()
        ledger_record = (ledger_resp.data or [None])[0]
        payout_id = ledger_record.get("id") if ledger_record else None
        if not payout_id:
            logger.warning("Failed to insert payout ledger", extra={"seller_id": seller_id})
            continue

        for item in line_items_payload:
            item["payout_id"] = payout_id
        client.table("payout_line_items").insert(line_items_payload).execute()

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
