from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings
from app.models.account_share import (
    AccountAccessibleOwner,
    AccountAccessibleOwnersResponse,
    AccountShareAcceptResponse,
    AccountShareDelegateListResponse,
    AccountShareDelegateShare,
    AccountShareInviteRequest,
    AccountShareInviteResponse,
    AccountShareOwnerListResponse,
    AccountShareOwnerShare,
    AccountShareSessionRequest,
    AccountShareSessionResponse,
)
from app.services import account_sharing, mailgun
from app.services.mailgun import MailgunRecipient
from app.utils.auth import (
    create_access_token,
    create_delegate_access_token,
    decode_access_token,
)


router = APIRouter(prefix="/account-share", tags=["account-share"])
security = HTTPBearer()


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def get_identity(credentials: Optional[HTTPAuthorizationCredentials]) -> tuple[str, str]:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証情報が必要です")
    payload = decode_access_token(credentials.credentials)
    owner_user_id = payload.get("sub")
    delegate_user_id = payload.get("delegate_id")
    if not owner_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")
    actor_user_id = delegate_user_id or owner_user_id
    return owner_user_id, actor_user_id


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        raise ValueError("datetime value is required")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@router.post("/invitations", response_model=AccountShareInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_account_share_invitation(
    payload: AccountShareInviteRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    owner_user_id, actor_user_id = get_identity(credentials)
    if owner_user_id != actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="共有招待の作成権限がありません")
    supabase = get_supabase()

    share = account_sharing.create_invitation(
        supabase,
        owner_id=owner_user_id,
        delegate_email=payload.email,
    )

    invite_token = share.get("invite_token")
    invite_url = f"{settings.frontend_url.rstrip('/')}/share/accept?token={invite_token}"

    if mailgun.is_configured():
        delegate_email = payload.email.strip()
        mailgun.send_bulk_email_async(
            subject="D-swipe アカウント共有招待",
            text=(
                "D-swipe のアカウント共有招待を受け取りました。\n"
                f"以下のリンクから承認してください: {invite_url}\n"
                "リンクの有効期限は数日間です。"
            ),
            html=None,
            recipients=[MailgunRecipient(email=delegate_email)],
            sender_email=settings.mailgun_default_from_email or "no-reply@d-swipe.com",
            sender_name=settings.mailgun_default_from_name or "D-swipe",
            reply_to=settings.mailgun_default_reply_to,
        )

    return AccountShareInviteResponse(
        share_id=share.get("id"),
        status=share.get("status"),
        expires_at=_to_datetime(share.get("expires_at")),
        invite_url=invite_url,
    )


@router.get("", response_model=AccountShareOwnerListResponse)
async def list_account_share_delegates(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    owner_user_id, actor_user_id = get_identity(credentials)
    if owner_user_id != actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="共有状況を確認する権限がありません")
    supabase = get_supabase()

    shares = account_sharing.list_owner_shares(supabase, owner_id=owner_user_id)
    items = [
        AccountShareOwnerShare(
            share_id=row.get("id"),
            delegate_user_id=row.get("delegate_user_id"),
            delegate_email=row.get("delegate_email"),
            delegate_username=row.get("delegate_username"),
            status=row.get("status"),
            invited_at=_to_datetime(row.get("invited_at")),
            accepted_at=_to_datetime(row.get("accepted_at")) if row.get("accepted_at") else None,
            expires_at=_to_datetime(row.get("expires_at")),
        )
        for row in shares
    ]
    return AccountShareOwnerListResponse(shares=items)


@router.get("/delegated", response_model=AccountShareDelegateListResponse)
async def list_account_share_owners(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _, actor_user_id = get_identity(credentials)
    supabase = get_supabase()

    shares = account_sharing.list_delegate_shares(supabase, delegate_id=actor_user_id)
    items = [
        AccountShareDelegateShare(
            share_id=row.get("id"),
            owner_user_id=row.get("owner_user_id"),
            owner_email=row.get("owner_email"),
            owner_username=row.get("owner_username"),
            status=row.get("status"),
            invited_at=_to_datetime(row.get("invited_at")),
            accepted_at=_to_datetime(row.get("accepted_at")) if row.get("accepted_at") else None,
            expires_at=_to_datetime(row.get("expires_at")),
        )
        for row in shares
    ]
    return AccountShareDelegateListResponse(shares=items)


@router.get("/accessible", response_model=AccountAccessibleOwnersResponse)
async def list_accessible_account_owners(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    owner_user_id, actor_user_id = get_identity(credentials)
    supabase = get_supabase()

    owners = account_sharing.list_accessible_owners(supabase, user_id=actor_user_id)
    return AccountAccessibleOwnersResponse(
        owners=[
            AccountAccessibleOwner(
                owner_user_id=owner.get("owner_user_id"),
                owner_email=owner.get("owner_email"),
                owner_username=owner.get("owner_username"),
                is_self=owner.get("owner_user_id") == actor_user_id,
            )
            for owner in owners
        ]
    )


@router.post("/invitations/{token}/accept", response_model=AccountShareAcceptResponse)
async def accept_account_share_invitation(
    token: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    owner_user_id, actor_user_id = get_identity(credentials)
    supabase = get_supabase()

    share = account_sharing.accept_invitation(
        supabase,
        token=token,
        delegate_user_id=actor_user_id,
    )

    return AccountShareAcceptResponse(
        share_id=share.get("id"),
        owner_user_id=share.get("owner_user_id"),
        delegate_user_id=share.get("delegate_user_id"),
        status=share.get("status"),
        accepted_at=_to_datetime(share.get("accepted_at")),
    )


@router.post("/sessions", response_model=AccountShareSessionResponse)
async def create_account_share_session(
    payload: AccountShareSessionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    owner_user_id, actor_user_id = get_identity(credentials)
    owner_user_id = payload.owner_user_id.strip()
    if not owner_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="owner_user_idを指定してください")

    supabase = get_supabase()
    # Verify access (raises if unauthorized)
    resolved_owner = account_sharing.resolve_acting_owner_id(
        supabase,
        actor_user_id=actor_user_id,
        requested_owner_id=owner_user_id,
    )

    if resolved_owner == actor_user_id:
        token = create_access_token(actor_user_id)
        delegate_id = None
    else:
        token = create_delegate_access_token(resolved_owner, actor_user_id)
        delegate_id = actor_user_id

    expires_in = settings.access_token_expires_minutes * 60
    return AccountShareSessionResponse(
        owner_user_id=resolved_owner,
        delegate_user_id=delegate_id,
        access_token=token,
        expires_in=expires_in,
    )


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_account_share(
    share_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    owner_user_id, actor_user_id = get_identity(credentials)
    supabase = get_supabase()

    if owner_user_id != actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="共有を解除する権限がありません")

    account_sharing.revoke_share(supabase, owner_id=owner_user_id, share_id=share_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
