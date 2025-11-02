from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.payouts import (
    PayoutDashboardResponse,
    PayoutLedgerEntry,
    PayoutSettings,
    PayoutSettingsUpsertRequest,
)
from app.services import payouts as payout_service
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/payouts", tags=["payouts"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def _get_current_user(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="トークンが必要です")

    try:
        payload = decode_access_token(credentials.credentials)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="トークンの検証に失敗しました")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

    return {"id": user_id}


@router.get("/dashboard", response_model=PayoutDashboardResponse)
async def get_payout_dashboard(credentials: HTTPAuthorizationCredentials = Depends(security)) -> PayoutDashboardResponse:
    user = _get_current_user(credentials)
    return payout_service.get_payout_dashboard(user["id"])


@router.get("/settings", response_model=Optional[PayoutSettings])
async def get_payout_settings(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[PayoutSettings]:
    user = _get_current_user(credentials)
    return payout_service.get_payout_settings(user_id=user["id"])


@router.put("/settings", response_model=PayoutSettings)
async def upsert_payout_settings(
    payload: PayoutSettingsUpsertRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> PayoutSettings:
    user = _get_current_user(credentials)
    if not payload.usdt_address or not payload.usdt_address.startswith("T"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TRC20アドレスを入力してください")
    return payout_service.upsert_payout_settings(user_id=user["id"], payload=payload, actor_id=user["id"])


@router.get("/ledger/{payout_id}", response_model=PayoutLedgerEntry)
async def get_payout_detail(
    payout_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> PayoutLedgerEntry:
    user = _get_current_user(credentials)
    entry = payout_service.get_payout_detail(payout_id)
    if not entry or entry.seller_id != user["id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="支払い情報が見つかりません")
    return entry
