from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.operator_messages import (
    OperatorMessageFeedResponse,
    OperatorMessageReadRequest,
    OperatorMessageUnreadCountResponse,
)
from app.services import operator_messages as message_service
from app.utils.auth import decode_access_token
from app.config import get_supabase_client


router = APIRouter(prefix="/messages", tags=["messages"])
security = HTTPBearer()


def _get_current_user(credentials: HTTPAuthorizationCredentials) -> dict:
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

    supabase = get_supabase_client()
    resp = (
        supabase
        .table("users")
        .select("id, username, email, user_type")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")
    return resp.data


@router.get("", response_model=OperatorMessageFeedResponse)
def list_inbox(
    filter_mode: str | None = Query(None, description="unread / read / archived"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    result = message_service.list_user_inbox(
        user_id=user["id"],
        limit=limit,
        offset=offset,
        filter_mode=filter_mode,
    )
    return OperatorMessageFeedResponse(**result)


@router.get("/unread-count", response_model=OperatorMessageUnreadCountResponse)
def unread_count(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _get_current_user(credentials)
    count = message_service.get_unread_count(user_id=user["id"])
    return OperatorMessageUnreadCountResponse(unread_count=count)


@router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    message_id: str,
    payload: OperatorMessageReadRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    try:
        message_service.mark_message(user_id=user["id"], message_id=message_id, payload=payload)
    except ValueError as exc:
        if str(exc) == "message_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")
        raise

    return None
