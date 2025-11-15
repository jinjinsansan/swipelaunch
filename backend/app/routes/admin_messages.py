from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.operator_messages import (
    OperatorMessageArchiveRequest,
    OperatorMessageCreateRequest,
    OperatorMessageHideRequest,
    OperatorMessageListResponse,
    OperatorMessageResponse,
    OperatorMessageUpdateRequest,
)
from app.routes.admin import require_admin
from app.services import operator_messages as message_service
from app.config import settings


def _require_super_admin(admin_user: Dict[str, Any]) -> None:
    email = (admin_user.get("email") or "").lower()
    allowed = [item.lower() for item in settings.operator_message_super_admin_emails]
    if email not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="この操作を行う権限がありません")


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/messages", tags=["admin-messages"])


def _raise_segment_error(exc: "message_service.SegmentResolutionError") -> None:
    code = exc.args[0] if exc.args else "segment_resolution_error"
    if code == "segment_email_not_found":
        detail: Dict[str, Any] = {
            "message": "存在しないメールアドレスが含まれています。",
            "missing_emails": exc.missing_emails,
        }
    elif code == "segment_email_empty":
        detail = {"message": "メールアドレスが入力されていません。"}
    else:
        detail = {"message": "配信対象の判定に失敗しました。"}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# pylint: disable=too-many-arguments
@router.get("", response_model=OperatorMessageListResponse)
def list_messages(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    visibility: str = Query("active", description="active/hidden/archived/all"),
    include_automated: bool = Query(False, description="自動送信メッセージも含める"),
    _admin=Depends(require_admin),
):
    try:
        result = message_service.list_messages(
            limit=limit,
            offset=offset,
            visibility=visibility,
            include_automated=include_automated,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不正な表示フィルターです")
    return OperatorMessageListResponse(**result)


@router.post("", response_model=OperatorMessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    payload: OperatorMessageCreateRequest,
    admin_user=Depends(require_admin),
):
    try:
        return message_service.create_message(payload, actor_id=admin_user.get("id"))
    except message_service.SegmentResolutionError as exc:
        _raise_segment_error(exc)
    except Exception as exc:
        logger.exception("Failed to create operator message: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="メッセージの作成に失敗しました")


@router.get("/{message_id}", response_model=OperatorMessageResponse)
def get_message_detail(
    message_id: str,
    _admin=Depends(require_admin),
):
    try:
        return message_service.get_message(message_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")


@router.patch("/{message_id}", response_model=OperatorMessageResponse)
def update_message(
    message_id: str,
    payload: OperatorMessageUpdateRequest,
    admin_user=Depends(require_admin),
):
    try:
        return message_service.update_message(message_id, payload, actor_id=admin_user.get("id"))
    except ValueError as exc:
        if str(exc) == "message_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")
        if str(exc) == "message_already_sent":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="送信済みのメッセージは編集できません")
        raise
    except message_service.SegmentResolutionError as exc:
        _raise_segment_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to update message %s: %s", message_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="メッセージの更新に失敗しました")


@router.post("/{message_id}/dispatch", status_code=status.HTTP_202_ACCEPTED)
def dispatch_message(
    message_id: str,
    _admin=Depends(require_admin),
):
    try:
        message_service.dispatch_message(message_id)
        return {"status": "ok"}
    except ValueError as exc:
        if str(exc) == "message_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")
        raise
    except message_service.SegmentResolutionError as exc:
        _raise_segment_error(exc)


@router.post("/process-due", status_code=status.HTTP_202_ACCEPTED)
def process_due_messages(_admin=Depends(require_admin)):
    processed = message_service.process_due_messages()
    return {"processed": processed}


@router.post("/{message_id}/hide", response_model=OperatorMessageResponse)
def hide_message(
    message_id: str,
    payload: OperatorMessageHideRequest,
    _admin=Depends(require_admin),
):
    try:
        return message_service.set_hidden(message_id, hidden=payload.hidden)
    except ValueError as exc:
        if str(exc) == "message_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")
        raise


@router.post("/{message_id}/archive", response_model=OperatorMessageResponse)
def archive_message(
    message_id: str,
    payload: OperatorMessageArchiveRequest,
    admin_user=Depends(require_admin),
):
    _require_super_admin(admin_user)
    try:
        return message_service.set_archived(message_id, archived=payload.archived)
    except ValueError as exc:
        if str(exc) == "message_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")
        raise


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    message_id: str,
    admin_user=Depends(require_admin),
):
    _require_super_admin(admin_user)
    try:
        message_service.delete_message(message_id)
    except ValueError as exc:
        if str(exc) == "message_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メッセージが見つかりません")
        raise
    return None
