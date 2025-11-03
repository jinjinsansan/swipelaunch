from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.operator_messages import (
    OperatorMessageCreateRequest,
    OperatorMessageListResponse,
    OperatorMessageResponse,
    OperatorMessageUpdateRequest,
)
from app.routes.admin import require_admin
from app.services import operator_messages as message_service


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/messages", tags=["admin-messages"])
security = HTTPBearer(auto_error=False)


@router.get("", response_model=OperatorMessageListResponse)
def list_messages(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin=Depends(require_admin),
):
    result = message_service.list_messages(limit=limit, offset=offset)
    return OperatorMessageListResponse(**result)


@router.post("", response_model=OperatorMessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    payload: OperatorMessageCreateRequest,
    admin_user=Depends(require_admin),
):
    try:
        return message_service.create_message(payload, actor_id=admin_user.get("id"))
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


@router.post("/process-due", status_code=status.HTTP_202_ACCEPTED)
def process_due_messages(_admin=Depends(require_admin)):
    processed = message_service.process_due_messages()
    return {"processed": processed}
