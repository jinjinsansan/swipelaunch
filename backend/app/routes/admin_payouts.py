from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.payouts import (
    AdminPayoutEventRequest,
    AdminPayoutGenerateRequest,
    AdminPayoutListFilters,
    AdminPayoutListResponse,
    AdminPayoutStatusUpdateRequest,
    AdminPayoutTxRecordRequest,
    AdminRiskOrderListResponse,
    PayoutLedgerEntry,
)
from app.routes.admin import require_admin
from app.services import payouts as payout_service


router = APIRouter(prefix="/admin/payouts", tags=["admin:payouts"])
security = HTTPBearer(auto_error=False)


def _admin_guard(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    return require_admin(credentials)  # type: ignore[arg-type]


@router.get("", response_model=AdminPayoutListResponse)
async def list_payouts(
    status_filter: Optional[str] = Query(None, alias="status"),
    seller_query: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin_user=Depends(_admin_guard),
) -> AdminPayoutListResponse:
    filters = AdminPayoutListFilters(
        status=status_filter,
        seller_query=seller_query,
        from_date=from_date,
        to_date=to_date,
    )
    return payout_service.list_admin_payouts(filters, limit=limit, offset=offset)


@router.get("/risk", response_model=AdminRiskOrderListResponse)
async def list_risk_orders(limit: int = Query(50, ge=1, le=200), admin_user=Depends(_admin_guard)) -> AdminRiskOrderListResponse:
    return payout_service.list_risk_orders(limit=limit)


@router.post("/generate")
async def generate_payouts(
    payload: AdminPayoutGenerateRequest,
    admin_user=Depends(_admin_guard),
) -> dict:
    result = payout_service.generate_payouts(payload, actor_id=admin_user.get("id"))
    return result


@router.get("/{payout_id}", response_model=PayoutLedgerEntry)
async def get_payout_detail(payout_id: str, admin_user=Depends(_admin_guard)) -> PayoutLedgerEntry:
    entry = payout_service.get_payout_detail(payout_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="支払い情報が見つかりません")
    return entry


@router.post("/{payout_id}/status", response_model=PayoutLedgerEntry)
async def update_status(
    payout_id: str,
    payload: AdminPayoutStatusUpdateRequest,
    admin_user=Depends(_admin_guard),
) -> PayoutLedgerEntry:
    entry = payout_service.update_payout_status(payout_id, payload, actor_id=admin_user.get("id"))
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="支払い情報が見つかりません")
    return entry


@router.post("/{payout_id}/transaction", response_model=PayoutLedgerEntry)
async def record_transaction(
    payout_id: str,
    payload: AdminPayoutTxRecordRequest,
    admin_user=Depends(_admin_guard),
) -> PayoutLedgerEntry:
    entry = payout_service.record_admin_transaction(payout_id, payload, actor_id=admin_user.get("id"))
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="支払い情報が見つかりません")
    return entry


@router.post("/{payout_id}/events")
async def create_event(
    payout_id: str,
    payload: AdminPayoutEventRequest,
    admin_user=Depends(_admin_guard),
) -> dict:
    event = payout_service.create_admin_event(payout_id, payload, actor_id=admin_user.get("id"))
    if hasattr(event, "dict"):
        return event.dict()
    return event
