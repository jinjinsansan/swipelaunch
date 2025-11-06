from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings
from app.models.team import (
    TeamInviteRequest,
    TeamInviteResponse,
    TeamMemberListResponse,
    TeamMemberResponse,
    TeamSummary,
    TeamUpdateMemberRequest,
)
from app.services import mailgun
from app.services.mailgun import MailgunRecipient
from app.services.team_access import (
    TeamContext,
    list_team_memberships,
    resolve_team_context,
)
from app.utils.auth import decode_access_token

router = APIRouter(prefix="/teams", tags=["teams"])
security = HTTPBearer()


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def get_current_user_id(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証情報が提供されていません")
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")
    return user_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_invite_expiry() -> datetime:
    days = getattr(settings, "team_invite_expiry_days", 7)
    try:
        days_value = int(days)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        days_value = 7
    return datetime.now(timezone.utc) + timedelta(days=days_value)


def _parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _log_team_action(
    supabase: Client,
    *,
    team_id: str,
    actor_id: Optional[str],
    action: str,
    target_user_id: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> None:
    log_payload = {
        "team_id": team_id,
        "actor_id": actor_id,
        "target_user_id": target_user_id,
        "action": action,
        "metadata": metadata or {},
        "created_at": _now_iso(),
    }
    supabase.table("team_audit_logs").insert(log_payload).execute()


def _build_team_summary_map(rows: List[Dict], contexts: List[TeamContext]) -> List[TeamSummary]:
    context_map = {ctx.team_id: ctx for ctx in contexts}
    summaries: List[TeamSummary] = []
    for row in rows:
        team_id = row.get("id")
        context = context_map.get(team_id)
        if not team_id or not context:
            continue
        summaries.append(
            TeamSummary(
                id=team_id,
                name=row.get("name"),
                owner_user_id=row.get("owner_user_id"),
                created_at=row.get("created_at"),
                role=context.role,
            )
        )
    return summaries


@router.get("/me", response_model=List[TeamSummary])
async def list_my_teams(credentials: HTTPAuthorizationCredentials = Depends(security)) -> List[TeamSummary]:
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    contexts = list_team_memberships(supabase, user_id)
    if not contexts:
        return []

    team_ids = [ctx.team_id for ctx in contexts]
    resp = (
        supabase
        .table("teams")
        .select("id, name, owner_user_id, created_at")
        .in_("id", team_ids)
        .execute()
    )
    rows = resp.data or []
    return _build_team_summary_map(rows, contexts)


def _fetch_user_map(supabase: Client, user_ids: List[str]) -> Dict[str, Dict]:
    if not user_ids:
        return {}
    resp = (
        supabase
        .table("users")
        .select("id, email, username, last_login_at")
        .in_("id", list(dict.fromkeys(user_ids)))
        .execute()
    )
    rows = resp.data or []
    return {row.get("id"): row for row in rows if row.get("id")}


@router.get("/{team_id}/members", response_model=TeamMemberListResponse)
async def get_team_members(
    team_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TeamMemberListResponse:
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    resolve_team_context(
        supabase,
        user_id,
        required_role="manager",
        team_id=team_id,
    )

    members_resp = (
        supabase
        .table("team_members")
        .select("user_id, role, status, invited_at, accepted_at")
        .eq("team_id", team_id)
        .execute()
    )
    member_rows = members_resp.data or []
    user_map = _fetch_user_map(supabase, [row.get("user_id") for row in member_rows if row.get("user_id")])

    members: List[TeamMemberResponse] = []
    for row in member_rows:
        member_id = row.get("user_id")
        user_info = user_map.get(member_id, {})
        members.append(
            TeamMemberResponse(
                user_id=member_id or "",
                email=user_info.get("email"),
                username=user_info.get("username"),
                role=row.get("role") or "manager",
                status=row.get("status") or "active",
                invited_at=_parse_datetime(row.get("invited_at")),
                accepted_at=_parse_datetime(row.get("accepted_at")),
                last_login_at=_parse_datetime(user_info.get("last_login_at")),
            )
        )

    return TeamMemberListResponse(team_id=team_id, members=members)


def _generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def _send_invitation_email(
    supabase: Client,
    *,
    team_row: Dict,
    invite_row: Dict,
    actor_user_id: str,
) -> None:
    sender_email = settings.mailgun_default_from_email or (f"no-reply@{settings.mailgun_domain}" if settings.mailgun_domain else None)
    recipient_email = invite_row.get("email")
    if not sender_email or not mailgun.is_configured() or not recipient_email:
        return

    actor_resp = (
        supabase
        .table("users")
        .select("username")
        .eq("id", actor_user_id)
        .maybe_single()
        .execute()
    )
    actor_username = (getattr(actor_resp, "data", None) or {}).get("username")

    team_name = team_row.get("name") or "D-swipe Team"
    invite_link = f"{settings.frontend_url}/team/invite?token={invite_row.get('token')}"

    subject = f"{team_name} へのチーム招待"
    expiry_days = getattr(settings, "team_invite_expiry_days", 7)
    lines = [
        f"{team_name} への招待が届きました。",
        "以下のリンクからログインして参加してください。",
        "",
        invite_link,
        "",
        "付与権限: 管理者",
    ]
    if actor_username:
        lines.append(f"招待者: {actor_username}")
    lines.extend([
        "",
        f"※このリンクは{expiry_days}日間有効です。",
        "",
        "D-swipe 事務局",
    ])

    mailgun.send_bulk_email_async(
        subject=subject,
        text="\n".join(lines),
        html=None,
        recipients=[MailgunRecipient(email=recipient_email)],
        sender_email=sender_email,
        sender_name=settings.mailgun_default_from_name or "D-swipe",
        reply_to=settings.mailgun_default_reply_to or "info@dlogicai.com",
    )


@router.post("/{team_id}/invitations", response_model=TeamInviteResponse)
async def create_team_invitation(
    team_id: str,
    payload: TeamInviteRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TeamInviteResponse:
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    resolve_team_context(
        supabase,
        user_id,
        required_role="manager",
        team_id=team_id,
    )

    email_lower = payload.email.lower()
    now_iso = _now_iso()
    expiry_dt = _compute_invite_expiry()

    # Prevent inviting an already active member
    existing_user_resp = (
        supabase
        .table("users")
        .select("id")
        .eq("email", email_lower)
        .maybe_single()
        .execute()
    )
    existing_user = getattr(existing_user_resp, "data", None)
    if existing_user and existing_user.get("id"):
        membership_resp = (
            supabase
            .table("team_members")
            .select("status")
            .eq("team_id", team_id)
            .eq("user_id", existing_user.get("id"))
            .maybe_single()
            .execute()
        )
        membership = getattr(membership_resp, "data", None)
        if membership and (membership.get("status") or "active") == "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="既にチームメンバーです")

    invitation_payload = {
        "team_id": team_id,
        "email": email_lower,
        "role": "manager",
        "token": _generate_invite_token(),
        "status": "pending",
        "invited_by": user_id,
        "invited_at": now_iso,
        "expires_at": expiry_dt.isoformat(),
        "updated_at": now_iso,
    }

    upsert_response = (
        supabase
        .table("team_invitations")
        .upsert(invitation_payload, on_conflict="team_id,email")
        .execute()
    )

    invite_row = (upsert_response.data or [None])[0]
    if not invite_row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="招待の作成に失敗しました")

    team_resp = (
        supabase
        .table("teams")
        .select("id, name")
        .eq("id", team_id)
        .maybe_single()
        .execute()
    )
    team_row = getattr(team_resp, "data", None) or {}

    _log_team_action(
        supabase,
        team_id=team_id,
        actor_id=user_id,
        action="invite_created",
        metadata={"email": email_lower, "role": "manager"},
    )

    _send_invitation_email(supabase, team_row=team_row, invite_row=invite_row, actor_user_id=user_id)

    return TeamInviteResponse(
        invitation_id=invite_row.get("id"),
        team_id=team_id,
        email=email_lower,
        role="manager",
        status=invite_row.get("status"),
        expires_at=_parse_datetime(invite_row.get("expires_at")) or expiry_dt,
    )


@router.post("/invitations/{token}/accept", response_model=TeamMemberResponse)
async def accept_invitation(
    token: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TeamMemberResponse:
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    invite_resp = (
        supabase
        .table("team_invitations")
        .select("id, team_id, email, role, status, expires_at")
        .eq("token", token)
        .maybe_single()
        .execute()
    )
    invitation = getattr(invite_resp, "data", None) or None
    if not invitation or invitation.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="有効な招待が見つかりません")

    expires_at = _parse_datetime(invitation.get("expires_at"))
    now_dt = datetime.now(timezone.utc)
    if expires_at and expires_at < now_dt:
        supabase.table("team_invitations").update({"status": "expired"}).eq("id", invitation["id"]).execute()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="招待の有効期限が切れています")

    team_id = invitation.get("team_id")

    user_resp = (
        supabase
        .table("users")
        .select("id, email, username, last_login_at")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    user_info = getattr(user_resp, "data", None) or {}

    invited_email = (invitation.get("email") or "").lower()
    user_email = (user_info.get("email") or "").lower()
    if invited_email and user_email and invited_email != user_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="招待されたメールアドレスと一致しません")

    # Ensure membership record
    members_resp = (
        supabase
        .table("team_members")
        .select("id, role, status")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    member_row = getattr(members_resp, "data", None)
    now_iso = now_dt.isoformat()

    if member_row:
        supabase.table("team_members").update({
            "role": invitation.get("role"),
            "status": "active",
            "accepted_at": now_iso,
            "updated_at": now_iso,
        }).eq("id", member_row.get("id")).execute()
    else:
        supabase.table("team_members").insert({
            "team_id": team_id,
            "user_id": user_id,
            "role": invitation.get("role"),
            "status": "active",
            "invited_at": now_iso,
            "accepted_at": now_iso,
        }).execute()

    supabase.table("team_invitations").update({
        "status": "accepted",
        "accepted_at": now_iso,
        "updated_at": now_iso,
    }).eq("id", invitation.get("id")).execute()

    _log_team_action(
        supabase,
        team_id=team_id,
        actor_id=user_id,
        action="invite_accepted",
        target_user_id=user_id,
    )

    return TeamMemberResponse(
        user_id=user_id,
        email=user_info.get("email"),
        username=user_info.get("username"),
        role=invitation.get("role") or "manager",
        status="active",
        invited_at=_parse_datetime(invitation.get("invited_at")),
        accepted_at=now_dt,
        last_login_at=_parse_datetime(user_info.get("last_login_at")),
    )


@router.patch("/{team_id}/members/{member_user_id}", response_model=TeamMemberResponse)
async def update_team_member(
    team_id: str,
    member_user_id: str,
    payload: TeamUpdateMemberRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TeamMemberResponse:
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    context = resolve_team_context(
        supabase,
        user_id,
        required_role="owner",
        team_id=team_id,
    )

    if member_user_id == context.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="オーナーの権限は変更できません")

    update_fields: Dict[str, str] = {}
    if payload.status:
        update_fields["status"] = payload.status

    if not update_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新内容が指定されていません")

    update_fields["updated_at"] = _now_iso()

    updated_resp = (
        supabase
        .table("team_members")
        .update(update_fields)
        .eq("team_id", team_id)
        .eq("user_id", member_user_id)
        .maybe_single()
        .execute()
    )
    updated_row = getattr(updated_resp, "data", None) or None
    if not updated_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メンバーが見つかりません")

    _log_team_action(
        supabase,
        team_id=team_id,
        actor_id=user_id,
        action="member_updated",
        target_user_id=member_user_id,
        metadata=update_fields,
    )

    user_map = _fetch_user_map(supabase, [member_user_id])
    user_info = user_map.get(member_user_id, {})

    return TeamMemberResponse(
        user_id=member_user_id,
        email=user_info.get("email"),
        username=user_info.get("username"),
        role=updated_row.get("role") or "manager",
        status=updated_row.get("status"),
        invited_at=_parse_datetime(updated_row.get("invited_at")),
        accepted_at=_parse_datetime(updated_row.get("accepted_at")),
        last_login_at=_parse_datetime(user_info.get("last_login_at")),
    )


@router.delete("/{team_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: str,
    member_user_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    context = resolve_team_context(
        supabase,
        user_id,
        required_role="owner",
        team_id=team_id,
    )

    if member_user_id == context.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="オーナーは削除できません")

    supabase.table("team_members").delete().eq("team_id", team_id).eq("user_id", member_user_id).execute()

    _log_team_action(
        supabase,
        team_id=team_id,
        actor_id=user_id,
        action="member_removed",
        target_user_id=member_user_id,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
