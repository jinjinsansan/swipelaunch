from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.followers import CreatorFollowRequest, CreatorFollowStatusResponse
from app.services import followers as follower_service
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/creators", tags=["creator-followers"])
security = HTTPBearer(auto_error=False)


def _get_optional_user_id(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        return None
    return payload.get("sub")


def _require_user_id(credentials: HTTPAuthorizationCredentials | None) -> str:
    user_id = _get_optional_user_id(credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証が必要です")
    return user_id


def _ensure_creator_exists(creator_id: str) -> None:
    client = get_supabase_client()
    creator = follower_service.fetch_creator(client, creator_id)
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")


@router.get("/{creator_id}/follow", response_model=CreatorFollowStatusResponse)
def get_creator_follow_status(
    creator_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    client = get_supabase_client()
    creator = follower_service.fetch_creator(client, creator_id)
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    follower_id = _get_optional_user_id(credentials)
    record = follower_service.get_follow_record(client, creator_id, follower_id) if follower_id else None
    follower_count = follower_service.count_followers(client, creator_id)

    return CreatorFollowStatusResponse(
        creator_id=creator_id,
        follower_id=follower_id,
        following=record is not None,
        notify_email=bool(record.get("notify_email", True)) if record else True,
        follower_count=follower_count,
        last_notified_at=record.get("last_notified_at") if record else None,
    )


@router.post("/{creator_id}/follow", response_model=CreatorFollowStatusResponse)
def follow_creator(
    creator_id: str,
    payload: CreatorFollowRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    follower_id = _require_user_id(credentials)
    if follower_id == creator_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自分自身をフォローすることはできません")

    client = get_supabase_client()
    creator = follower_service.fetch_creator(client, creator_id)
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    notify_email = payload.notify_email if payload and payload.notify_email is not None else True
    follower_service.follow_creator(client, creator_id, follower_id, notify_email=notify_email)
    record = follower_service.get_follow_record(client, creator_id, follower_id)
    follower_count = follower_service.count_followers(client, creator_id)

    return CreatorFollowStatusResponse(
        creator_id=creator_id,
        follower_id=follower_id,
        following=True,
        notify_email=bool(record.get("notify_email", True)) if record else notify_email,
        follower_count=follower_count,
        last_notified_at=record.get("last_notified_at") if record else None,
    )


@router.patch("/{creator_id}/follow", response_model=CreatorFollowStatusResponse)
def update_follow_preferences(
    creator_id: str,
    payload: CreatorFollowRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    follower_id = _require_user_id(credentials)
    client = get_supabase_client()

    creator = follower_service.fetch_creator(client, creator_id)
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    record = follower_service.get_follow_record(client, creator_id, follower_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="フォロー情報が見つかりません")

    if payload.notify_email is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新内容が指定されていません")

    updated = follower_service.update_follow_preferences(
        client,
        creator_id,
        follower_id,
        notify_email=payload.notify_email,
    )
    follower_count = follower_service.count_followers(client, creator_id)

    return CreatorFollowStatusResponse(
        creator_id=creator_id,
        follower_id=follower_id,
        following=True,
        notify_email=bool(updated.get("notify_email", True)) if updated else bool(record.get("notify_email", True)),
        follower_count=follower_count,
        last_notified_at=updated.get("last_notified_at") if updated else record.get("last_notified_at"),
    )


@router.delete("/{creator_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def unfollow_creator(
    creator_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    follower_id = _require_user_id(credentials)
    client = get_supabase_client()

    creator = follower_service.fetch_creator(client, creator_id)
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    follower_service.unfollow_creator(client, creator_id, follower_id)
    return None
