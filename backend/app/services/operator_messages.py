from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from supabase import Client, create_client

from app.config import settings
from app.models.operator_messages import (
    OperatorMessageCreateRequest,
    OperatorMessageReadRequest,
    OperatorMessageResponse,
    OperatorMessageSegment,
    OperatorMessageUpdateRequest,
)

logger = logging.getLogger(__name__)


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


class SegmentResolutionError(ValueError):
    def __init__(self, message: str = "segment_resolution_error", *, missing_emails: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.missing_emails = missing_emails or []


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_list(value: Optional[Iterable[OperatorMessageSegment]]) -> List[OperatorMessageSegment]:
    if not value:
        return []
    return list(value)


def _parse_email_values(raw: Any) -> List[str]:
    if isinstance(raw, list):
        candidates = [str(item) for item in raw]
    elif isinstance(raw, str):
        candidates = re.split(r"[\s,;]+", raw)
    else:
        candidates = []
    return [candidate.strip() for candidate in candidates if candidate and candidate.strip()]


def _collect_emails_from_segments(segments: Sequence[OperatorMessageSegment]) -> Set[str]:
    emails: Set[str] = set()
    for segment in segments:
        if (segment.segment_type or "").lower() != "emails":
            continue
        payload = segment.segment_payload if isinstance(segment.segment_payload, dict) else {}
        for email in _parse_email_values(payload.get("emails")):
            emails.add(email.lower())
    return emails


def _validate_segments(client: Client, segments: Sequence[OperatorMessageSegment]) -> None:
    if not segments:
        return

    has_email_segment = False
    for segment in segments:
        if (segment.segment_type or "").lower() != "emails":
            continue
        has_email_segment = True
        payload = segment.segment_payload if isinstance(segment.segment_payload, dict) else {}
        values = _parse_email_values(payload.get("emails"))
        if not values:
            raise SegmentResolutionError("segment_email_empty")

    if has_email_segment:
        _lookup_users_by_emails(client, _collect_emails_from_segments(segments))


def _lookup_users_by_emails(client: Client, emails: Set[str]) -> Dict[str, str]:
    if not emails:
        return {}

    resp = (
        client
        .table("users")
        .select("id, email")
        .in_("email", list(emails))
        .execute()
    )

    found: Dict[str, str] = {}
    for row in resp.data or []:
        email = (row.get("email") or "").strip().lower()
        user_id = row.get("id")
        if email and user_id:
            found[email] = user_id

    missing = sorted(email for email in emails if email not in found)
    if missing:
        raise SegmentResolutionError("segment_email_not_found", missing_emails=missing)

    return found


def _map_message(row: Dict[str, Any], *, segments: Optional[List[Dict[str, Any]]] = None) -> OperatorMessageResponse:
    return OperatorMessageResponse(
        id=str(row.get("id")),
        title=row.get("title", ""),
        body_text=row.get("body_text"),
        body_html=row.get("body_html"),
        category=row.get("category", "general"),
        priority=row.get("priority", "normal"),
        status=row.get("status", "draft"),
        send_at=_parse_datetime(row.get("send_at")),
        created_by=row.get("created_by"),
        created_at=_parse_datetime(row.get("created_at")) or _utcnow(),
        updated_at=_parse_datetime(row.get("updated_at")) or _utcnow(),
        segment_summary=[
            OperatorMessageSegment(
                segment_type=segment.get("segment_type", "all_sellers"),
                segment_payload=segment.get("segment_payload") or {},
            )
            for segment in segments or []
        ],
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _fetch_segments(client: Client, message_id: str) -> List[Dict[str, Any]]:
    segment_resp = (
        client
        .table("operator_message_segments")
        .select("segment_type, segment_payload")
        .eq("message_id", message_id)
        .execute()
    )
    return segment_resp.data or []


def _resolve_recipient_ids(client: Client, segments: Sequence[OperatorMessageSegment]) -> List[str]:
    if not segments:
        segments = [OperatorMessageSegment(segment_type="all_sellers")]

    recipient_ids: List[str] = []
    seen = set()
    email_lookup = _lookup_users_by_emails(client, _collect_emails_from_segments(segments))

    for segment in segments:
        segment_type = segment.segment_type or "all_sellers"
        if segment_type == "all_sellers":
            resp = (
                client
                .table("users")
                .select("id, user_type")
                .eq("user_type", "seller")
                .execute()
            )
            for row in resp.data or []:
                user_id = row.get("id")
                if user_id and user_id not in seen:
                    seen.add(user_id)
                    recipient_ids.append(user_id)
        elif segment_type == "all_users":
            resp = client.table("users").select("id").execute()
            for row in resp.data or []:
                user_id = row.get("id")
                if user_id and user_id not in seen:
                    seen.add(user_id)
                    recipient_ids.append(user_id)
        elif segment_type == "user_ids":
            ids = segment.segment_payload.get("user_ids") if isinstance(segment.segment_payload, dict) else None
            if isinstance(ids, list):
                for user_id in ids:
                    if isinstance(user_id, str) and user_id and user_id not in seen:
                        seen.add(user_id)
                        recipient_ids.append(user_id)
        elif segment_type == "emails":
            payload = segment.segment_payload if isinstance(segment.segment_payload, dict) else {}
            for email in _parse_email_values(payload.get("emails")):
                normalized = email.lower()
                user_id = email_lookup.get(normalized)
                if user_id and user_id not in seen:
                    seen.add(user_id)
                    recipient_ids.append(user_id)
        else:
            logger.warning("Unsupported segment type %s; skipping", segment_type)

    return recipient_ids


def create_message(payload: OperatorMessageCreateRequest, *, actor_id: Optional[str]) -> OperatorMessageResponse:
    client = get_supabase()
    segments = _ensure_list(payload.target_segments)

    _validate_segments(client, segments)

    insert_data = {
        "title": payload.title,
        "body_text": payload.body_text,
        "body_html": payload.body_html,
        "category": payload.category,
        "priority": payload.priority,
        "status": "scheduled" if (payload.send_at and payload.send_at > _utcnow() and not payload.send_now) else "draft",
        "send_at": payload.send_at.isoformat() if payload.send_at else None,
        "created_by": actor_id,
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
    }

    response = client.table("operator_messages").insert(insert_data).execute()
    if not response.data:
        raise RuntimeError("Failed to insert operator message")

    message_row = response.data[0]
    message_id = message_row.get("id")

    if message_id and segments:
        segment_payload = [
            {
                "message_id": message_id,
                "segment_type": segment.segment_type,
                "segment_payload": segment.segment_payload,
            }
            for segment in segments
        ]
        client.table("operator_message_segments").insert(segment_payload).execute()

    if payload.send_now or (payload.send_at and payload.send_at <= _utcnow()):
        dispatch_message(message_id, client=client)
    else:
        # Update status explicitly to scheduled
        client.table("operator_messages").update({"status": "scheduled"}).eq("id", message_id).execute()

    segments_rows = _fetch_segments(client, message_id)
    refreshed = client.table("operator_messages").select("*").eq("id", message_id).single().execute()
    return _map_message(refreshed.data, segments=segments_rows)


def update_message(message_id: str, payload: OperatorMessageUpdateRequest, *, actor_id: Optional[str]) -> OperatorMessageResponse:
    client = get_supabase()
    current_resp = client.table("operator_messages").select("*").eq("id", message_id).single().execute()
    if not current_resp.data:
        raise ValueError("message_not_found")

    current = current_resp.data
    status = current.get("status", "draft")
    if status == "sent":
        raise ValueError("message_already_sent")

    update_fields: Dict[str, Any] = {}
    if payload.title is not None:
        update_fields["title"] = payload.title
    if payload.body_text is not None:
        update_fields["body_text"] = payload.body_text
    if payload.body_html is not None:
        update_fields["body_html"] = payload.body_html
    if payload.category is not None:
        update_fields["category"] = payload.category
    if payload.priority is not None:
        update_fields["priority"] = payload.priority
    if payload.send_at is not None:
        update_fields["send_at"] = payload.send_at.isoformat()
    update_fields["updated_at"] = _utcnow().isoformat()

    if update_fields:
        client.table("operator_messages").update(update_fields).eq("id", message_id).execute()

    if payload.target_segments is not None:
        segments = _ensure_list(payload.target_segments)
        _validate_segments(client, segments)
        client.table("operator_message_segments").delete().eq("message_id", message_id).execute()
        if segments:
            client.table("operator_message_segments").insert([
                {
                    "message_id": message_id,
                    "segment_type": segment.segment_type,
                    "segment_payload": segment.segment_payload,
                }
                for segment in segments
            ]).execute()

    refreshed = client.table("operator_messages").select("*").eq("id", message_id).single().execute()
    segments_rows = _fetch_segments(client, message_id)
    return _map_message(refreshed.data, segments=segments_rows)


def dispatch_message(message_id: str, *, client: Optional[Client] = None) -> None:
    client = client or get_supabase()
    message_resp = client.table("operator_messages").select("*").eq("id", message_id).single().execute()
    if not message_resp.data:
        raise ValueError("message_not_found")

    message = message_resp.data
    if message.get("status") == "sent":
        return

    segments_rows = _fetch_segments(client, message_id)
    segments = [
        OperatorMessageSegment(
            segment_type=row.get("segment_type", "all_sellers"),
            segment_payload=row.get("segment_payload") or {},
        )
        for row in segments_rows
    ]

    recipient_ids = _resolve_recipient_ids(client, segments)
    if not recipient_ids:
        logger.info("No recipients resolved for message %s", message_id)
        client.table("operator_messages").update({"status": "sent", "send_at": message.get("send_at") or _utcnow().isoformat()}).eq("id", message_id).execute()
        return

    existing_resp = (
        client
        .table("operator_message_recipients")
        .select("user_id")
        .eq("message_id", message_id)
        .execute()
    )
    existing_ids = {row.get("user_id") for row in (existing_resp.data or []) if row.get("user_id")}

    new_rows = [
        {
            "message_id": message_id,
            "user_id": user_id,
            "delivery_status": "delivered",
            "archived": False,
            "read_at": None,
            "created_at": _utcnow().isoformat(),
            "updated_at": _utcnow().isoformat(),
        }
        for user_id in recipient_ids
        if user_id not in existing_ids
    ]
    if new_rows:
        client.table("operator_message_recipients").insert(new_rows).execute()

    send_at = message.get("send_at")
    if not send_at:
        send_at = _utcnow().isoformat()
    client.table("operator_messages").update({"status": "sent", "send_at": send_at}).eq("id", message_id).execute()


def process_due_messages(*, client: Optional[Client] = None) -> int:
    client = client or get_supabase()
    now_iso = _utcnow().isoformat()
    due_resp = (
        client
        .table("operator_messages")
        .select("id")
        .in_("status", ["draft", "scheduled"])
        .lte("send_at", now_iso)
        .execute()
    )
    processed = 0
    for row in due_resp.data or []:
        message_id = row.get("id")
        if not message_id:
            continue
        try:
            dispatch_message(message_id, client=client)
            processed += 1
        except Exception as exc:  # pragma: no cover - logging
            logger.exception("Failed to dispatch message %s: %s", message_id, exc)
    return processed


def list_messages(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    client = get_supabase()
    resp = (
        client
        .table("operator_messages")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    messages = resp.data or []
    message_ids = [row.get("id") for row in messages if row.get("id")]
    segments_map: Dict[str, List[Dict[str, Any]]] = {}
    if message_ids:
        segment_resp = (
            client
            .table("operator_message_segments")
            .select("message_id, segment_type, segment_payload")
            .in_("message_id", message_ids)
            .execute()
        )
        for row in segment_resp.data or []:
            message_id = row.get("message_id")
            if not message_id:
                continue
            segments_map.setdefault(message_id, []).append(row)

    mapped = [_map_message(row, segments=segments_map.get(row.get("id"), [])) for row in messages]
    total = getattr(resp, "count", None) or len(mapped)
    return {"data": mapped, "total": total, "limit": limit, "offset": offset}


def get_message(message_id: str) -> OperatorMessageResponse:
    client = get_supabase()
    resp = client.table("operator_messages").select("*").eq("id", message_id).single().execute()
    if not resp.data:
        raise ValueError("message_not_found")
    segments = _fetch_segments(client, message_id)
    return _map_message(resp.data, segments=segments)


def list_user_inbox(*, user_id: str, limit: int = 50, offset: int = 0, filter_mode: Optional[str] = None) -> Dict[str, Any]:
    client = get_supabase()
    query = (
        client
        .table("operator_message_recipients")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )

    include_archived = filter_mode == "archived"
    query = query.eq("archived", include_archived)

    if filter_mode == "unread":
        query = query.is_("read_at", "null")

    resp = query.execute()
    recipients = resp.data or []

    if filter_mode == "read":
        recipients = [row for row in recipients if row.get("read_at")]
    elif filter_mode == "unread":
        recipients = [row for row in recipients if not row.get("read_at")]
    message_ids = [row.get("message_id") for row in recipients if row.get("message_id")]
    messages_map: Dict[str, Dict[str, Any]] = {}
    if message_ids:
        messages_resp = (
            client
            .table("operator_messages")
            .select("*")
            .in_("id", message_ids)
            .execute()
        )
        for row in messages_resp.data or []:
            if row.get("id"):
                messages_map[row["id"]] = row

    mapped = []
    for row in recipients:
        message_id = row.get("message_id")
        message_row = messages_map.get(message_id or "")
        if not message_row:
            continue
        mapped.append({
            "id": row.get("id"),
            "message_id": message_id,
            "user_id": user_id,
            "title": message_row.get("title"),
            "body_text": message_row.get("body_text"),
            "body_html": message_row.get("body_html"),
            "category": message_row.get("category", "general"),
            "priority": message_row.get("priority", "normal"),
            "delivery_status": row.get("delivery_status", "delivered"),
            "read_at": _parse_datetime(row.get("read_at")),
            "archived": bool(row.get("archived", False)),
            "send_at": _parse_datetime(message_row.get("send_at")) or _parse_datetime(row.get("created_at")),
            "created_at": _parse_datetime(row.get("created_at")) or _utcnow(),
        })

    total = len(mapped) if filter_mode in {"read", "unread"} else getattr(resp, "count", None) or len(mapped)
    return {"data": mapped, "total": total, "limit": limit, "offset": offset}


def get_unread_count(*, user_id: str) -> int:
    client = get_supabase()
    resp = (
        client
        .table("operator_message_recipients")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("archived", False)
        .is_("read_at", "null")
        .execute()
    )
    return getattr(resp, "count", None) or 0


def mark_message(user_id: str, message_id: str, payload: OperatorMessageReadRequest) -> None:
    client = get_supabase()
    recipient_resp = (
        client
        .table("operator_message_recipients")
        .select("id, read_at, archived")
        .eq("user_id", user_id)
        .eq("message_id", message_id)
        .single()
        .execute()
    )
    if not recipient_resp.data:
        raise ValueError("message_not_found")

    updates: Dict[str, Any] = {"updated_at": _utcnow().isoformat()}
    if payload.read:
        updates["read_at"] = _utcnow().isoformat()
    else:
        updates["read_at"] = None
    if payload.archive is not None:
        updates["archived"] = payload.archive

    client.table("operator_message_recipients").update(updates).eq("id", recipient_resp.data["id"]).execute()
