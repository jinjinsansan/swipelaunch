from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException, status

from app.config import settings

INVITE_STATUS_PENDING = "pending"
INVITE_STATUS_ACTIVE = "active"
INVITE_STATUS_REVOKED = "revoked"
VALID_STATUSES = {INVITE_STATUS_PENDING, INVITE_STATUS_ACTIVE, INVITE_STATUS_REVOKED}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_expiry() -> datetime:
    days = settings.account_share_invite_expiry_days or 7
    if days < 1:
        days = 7
    return _now() + timedelta(days=days)


def _get_single(supabase, query):
    response = query.maybe_single().execute()
    return getattr(response, "data", None)


def _list_rows(supabase, query) -> List[Dict]:
    response = query.execute()
    return response.data or []


def _get_user_by_email(supabase, email: str) -> Optional[Dict]:
    if not email:
        return None
    email = email.strip().lower()
    return _get_single(
        supabase,
        supabase
        .table("users")
        .select("id, email, username")
        .eq("email", email)
    )


def _get_user_map(supabase, user_ids: List[str]) -> Dict[str, Dict]:
    if not user_ids:
        return {}
    response = supabase.table("users").select("id, email, username").in_("id", user_ids).execute()
    rows = response.data or []
    return {row.get("id"): row for row in rows if row.get("id")}


def _get_share_row(supabase, *, owner_id: str, delegate_id: str) -> Optional[Dict]:
    return _get_single(
        supabase,
        supabase
        .table("account_shares")
        .select("*")
        .eq("owner_user_id", owner_id)
        .eq("delegate_user_id", delegate_id)
    )


def _get_share_by_token(supabase, token: str) -> Optional[Dict]:
    if not token:
        return None
    return _get_single(
        supabase,
        supabase
        .table("account_shares")
        .select("*")
        .eq("invite_token", token)
    )


def create_invitation(supabase, *, owner_id: str, delegate_email: str) -> Dict:
    delegate_user = _get_user_by_email(supabase, delegate_email)
    if not delegate_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="招待するユーザーが見つかりません")

    delegate_id = delegate_user.get("id")
    if not delegate_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="招待するユーザー情報が不正です")

    if delegate_id == owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自分自身を招待することはできません")

    existing = _get_share_row(supabase, owner_id=owner_id, delegate_id=delegate_id)
    if existing and existing.get("status") == INVITE_STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="すでに共有済みのユーザーです")

    now = _now()
    expires_at = _compute_expiry()
    invite_token = str(uuid4())

    payload = {
        "owner_user_id": owner_id,
        "delegate_user_id": delegate_id,
        "status": INVITE_STATUS_PENDING,
        "invite_token": invite_token,
        "invited_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "accepted_at": None,
        "revoked_at": None,
        "updated_at": now.isoformat(),
    }

    if existing and existing.get("id"):
        payload["id"] = existing["id"]

    response = supabase.table("account_shares").upsert(
        payload,
        on_conflict="owner_user_id,delegate_user_id",
    ).execute()

    if not response.data:
        saved = _get_share_row(supabase, owner_id=owner_id, delegate_id=delegate_id)
    else:
        saved = response.data[0]

    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="共有招待の作成に失敗しました")

    return saved


def accept_invitation(supabase, *, token: str, delegate_user_id: str) -> Dict:
    share = _get_share_by_token(supabase, token)
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="招待が見つかりません")

    if share.get("status") != INVITE_STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="この招待は無効です")

    if share.get("delegate_user_id") != delegate_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="この招待にアクセスする権限がありません")

    expires_at = share.get("expires_at")
    if expires_at:
        try:
            expiry_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            expiry_dt = None
        if expiry_dt and expiry_dt < _now():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="招待の有効期限が切れています")

    now = _now().isoformat()
    response = (
        supabase
        .table("account_shares")
        .update({
            "status": INVITE_STATUS_ACTIVE,
            "accepted_at": now,
            "updated_at": now,
        })
        .eq("id", share.get("id"))
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="招待の承認に失敗しました")

    return response.data[0]


def revoke_share(supabase, *, owner_id: str, share_id: str) -> None:
    share = _get_single(
        supabase,
        supabase
        .table("account_shares")
        .select("id, owner_user_id")
        .eq("id", share_id)
    )
    if not share or share.get("owner_user_id") != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="共有情報が見つかりません")

    now = _now().isoformat()
    supabase.table("account_shares").update(
        {
            "status": INVITE_STATUS_REVOKED,
            "revoked_at": now,
            "updated_at": now,
        }
    ).eq("id", share_id).execute()


def list_owner_shares(supabase, *, owner_id: str) -> List[Dict]:
    rows = _list_rows(
        supabase,
        supabase
        .table("account_shares")
        .select("*")
        .eq("owner_user_id", owner_id)
        .order("invited_at", desc=True)
    )
    user_map = _get_user_map(supabase, [row.get("delegate_user_id") for row in rows])
    for row in rows:
        delegate = user_map.get(row.get("delegate_user_id"), {})
        row["delegate_email"] = delegate.get("email")
        row["delegate_username"] = delegate.get("username")
    return rows


def list_delegate_shares(supabase, *, delegate_id: str) -> List[Dict]:
    rows = _list_rows(
        supabase,
        supabase
        .table("account_shares")
        .select("*")
        .eq("delegate_user_id", delegate_id)
        .order("invited_at", desc=True)
    )
    owner_map = _get_user_map(supabase, [row.get("owner_user_id") for row in rows])
    for row in rows:
        owner = owner_map.get(row.get("owner_user_id"), {})
        row["owner_email"] = owner.get("email")
        row["owner_username"] = owner.get("username")
    return rows


def get_accessible_owner_ids(supabase, *, user_id: str) -> List[str]:
    rows = _list_rows(
        supabase,
        supabase
        .table("account_shares")
        .select("owner_user_id")
        .eq("delegate_user_id", user_id)
        .eq("status", INVITE_STATUS_ACTIVE)
    )
    owner_ids = [row.get("owner_user_id") for row in rows if row.get("owner_user_id")]
    # Ensure uniqueness while preserving order
    seen = set()
    accessible = [user_id]
    for owner_id in owner_ids:
        if owner_id and owner_id not in seen and owner_id != user_id:
            accessible.append(owner_id)
            seen.add(owner_id)
    return accessible


def list_accessible_owners(supabase, *, user_id: str) -> List[Dict]:
    owner_ids = get_accessible_owner_ids(supabase, user_id=user_id)
    owner_map = _get_user_map(supabase, owner_ids)
    owners: List[Dict] = []
    for owner_id in owner_ids:
        owner = owner_map.get(owner_id, {})
        owners.append(
            {
                "owner_user_id": owner_id,
                "owner_email": owner.get("email"),
                "owner_username": owner.get("username"),
                "is_self": owner_id == user_id,
            }
        )
    return owners


def resolve_acting_owner_id(supabase, *, actor_user_id: str, requested_owner_id: Optional[str]) -> str:
    if not requested_owner_id or requested_owner_id == actor_user_id:
        return actor_user_id

    share = _get_single(
        supabase,
        supabase
        .table("account_shares")
        .select("status")
        .eq("owner_user_id", requested_owner_id)
        .eq("delegate_user_id", actor_user_id)
        .eq("status", INVITE_STATUS_ACTIVE)
    )

    if not share:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="共有されたアカウントにアクセスできません")

    return requested_owner_id


def ensure_actor_can_manage_owner(supabase, *, actor_user_id: str, owner_user_id: str) -> None:
    resolve_acting_owner_id(supabase, actor_user_id=actor_user_id, requested_owner_id=owner_user_id)
