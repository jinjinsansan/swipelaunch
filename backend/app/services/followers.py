from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from supabase import Client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_creator(client: Client, creator_id: str) -> Optional[Dict[str, object]]:
    resp = (
        client
        .table("users")
        .select("id, username, display_name")
        .eq("id", creator_id)
        .single()
        .execute()
    )
    if not resp.data:
        return None
    return resp.data


def get_follow_record(client: Client, creator_id: str, follower_id: str) -> Optional[Dict[str, object]]:
    resp = (
        client
        .table("creator_followers")
        .select("creator_id, follower_id, notify_email, last_notified_at")
        .eq("creator_id", creator_id)
        .eq("follower_id", follower_id)
        .maybe_single()
        .execute()
    )
    return resp.data if resp and getattr(resp, "data", None) else None


def count_followers(client: Client, creator_id: str) -> int:
    resp = (
        client
        .table("creator_followers")
        .select("id", count="exact")
        .eq("creator_id", creator_id)
        .execute()
    )
    return getattr(resp, "count", None) or 0


def follow_creator(client: Client, creator_id: str, follower_id: str, *, notify_email: Optional[bool] = None) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "creator_id": creator_id,
        "follower_id": follower_id,
        "updated_at": _now_iso(),
    }
    if notify_email is not None:
        payload["notify_email"] = notify_email

    resp = (
        client
        .table("creator_followers")
        .upsert(payload, on_conflict="creator_id,follower_id")
        .execute()
    )
    if not resp.data:
        logger.warning("Failed to upsert creator_followers for %s -> %s", follower_id, creator_id)
        return payload
    return resp.data[0]


def update_follow_preferences(client: Client, creator_id: str, follower_id: str, *, notify_email: Optional[bool] = None) -> Optional[Dict[str, object]]:
    updates: Dict[str, object] = {"updated_at": _now_iso()}
    if notify_email is not None:
        updates["notify_email"] = notify_email

    resp = (
        client
        .table("creator_followers")
        .update(updates)
        .eq("creator_id", creator_id)
        .eq("follower_id", follower_id)
        .execute()
    )
    if not resp.data:
        return None
    return resp.data[0]


def unfollow_creator(client: Client, creator_id: str, follower_id: str) -> None:
    client.table("creator_followers").delete().eq("creator_id", creator_id).eq("follower_id", follower_id).execute()


def list_followers(client: Client, creator_id: str) -> List[Dict[str, object]]:
    resp = (
        client
        .table("creator_followers")
        .select("follower_id, notify_email, last_notified_at")
        .eq("creator_id", creator_id)
        .execute()
    )
    return resp.data or []
