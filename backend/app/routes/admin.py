
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from supabase import Client, create_client

from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBearer()
logger = logging.getLogger(__name__)

ADMIN_EMAILS = {
    "goldbenchan@gmail.com",
    "kusanokiyoshi1@gmail.com",
}


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        cleaned = value.replace('Z', '+00:00') if value.endswith('Z') else value
        return datetime.fromisoformat(cleaned)
    except Exception:
        return None


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_current_user(credentials: HTTPAuthorizationCredentials) -> dict:
    try:
        token = credentials.credentials
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです",
            )
        supabase = get_supabase()
        user_response = (
            supabase
            .table("users")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません",
            )
        return user_response.data
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました",
        )


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = get_current_user(credentials)
    email = user.get("email")
    if email not in ADMIN_EMAILS and not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者権限が必要です",
        )
    return user


def create_moderation_event(
    supabase: Client,
    *,
    action: str,
    performed_by: Optional[str],
    target_user_id: Optional[str] = None,
    target_lp_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    event = {
        "action": action,
        "performed_by": performed_by,
        "target_user_id": target_user_id,
        "target_lp_id": target_lp_id,
        "reason": reason,
        "created_at": now_utc_iso(),
    }
    try:
        supabase.table("moderation_events").insert(event).execute()
    except Exception as exc:  # pragma: no cover - logging only
        logger.warning("Failed to record moderation event: %s", exc)


def handle_supabase_response(response, context: str) -> Tuple[Any, Optional[int]]:
    error = getattr(response, "error", None)
    if error:
        message = getattr(error, "message", None) or str(error)
        logger.error("Supabase error in %s: %s", context, message)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{context}: {message}",
        )
    data = response.data or []
    count = getattr(response, "count", None)
    return data, count


class GrantPointsRequest(BaseModel):
    user_id: str
    amount: int
    description: Optional[str] = "管理者によるポイント付与"


class GrantPointsResponse(BaseModel):
    transaction_id: str
    user_id: str
    username: str
    amount: int
    new_balance: int
    description: str
    granted_at: str


class UserSearchResponse(BaseModel):
    id: str
    username: str
    email: str
    user_type: str
    point_balance: int
    created_at: str


class UserListResponse(BaseModel):
    data: List[UserSearchResponse]
    total: int


class AdminUserSummarySchema(BaseModel):
    id: str
    username: str
    email: str
    user_type: str
    point_balance: int
    created_at: str
    is_blocked: bool = False
    blocked_reason: Optional[str] = None
    blocked_at: Optional[str] = None
    total_lp_count: int = 0
    total_product_count: int = 0
    total_point_purchased: int = 0
    total_point_spent: int = 0
    total_point_granted: int = 0
    latest_activity: Optional[str] = None


class AdminUserListResponse(BaseModel):
    data: List[AdminUserSummarySchema]
    total: int


class AdminPointTransactionSchema(BaseModel):
    id: str
    transaction_type: str
    amount: int
    description: Optional[str] = None
    created_at: str
    related_product_id: Optional[str] = None


class AdminUserLandingPageSchema(BaseModel):
    id: str
    title: str
    status: str
    slug: str
    total_views: int
    total_cta_clicks: int
    created_at: str
    updated_at: str


class AdminUserPurchaseSchema(BaseModel):
    transaction_id: str
    product_id: Optional[str] = None
    product_title: Optional[str] = None
    amount: int
    created_at: str
    description: Optional[str] = None


class AdminUserDetailResponse(AdminUserSummarySchema):
    transactions: List[AdminPointTransactionSchema]
    landing_pages: List[AdminUserLandingPageSchema]
    purchase_history: List[AdminUserPurchaseSchema]


class UserActionResponse(BaseModel):
    success: bool = True
    user_id: Optional[str]
    message: str


class BlockUserRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=400)


class LPStatusUpdateRequest(BaseModel):
    status: Literal['published', 'archived']
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminMarketplaceItemSchema(BaseModel):
    id: str
    title: str
    slug: str
    status: str
    seller_id: str
    seller_username: str
    seller_email: str
    total_views: int
    total_cta_clicks: int
    created_at: str
    updated_at: str
    product_count: int


class AdminMarketplaceResponse(BaseModel):
    data: List[AdminMarketplaceItemSchema]
    total: int


class PointAnalyticsTotalsSchema(BaseModel):
    purchased: int
    spent: int
    granted: int
    other: int
    net: int


class PointAnalyticsBreakdownSchema(BaseModel):
    label: str
    purchased: int
    spent: int
    granted: int
    other: int
    net: int


class PointAnalyticsResponse(BaseModel):
    totals: PointAnalyticsTotalsSchema
    daily: List[PointAnalyticsBreakdownSchema]
    monthly: List[PointAnalyticsBreakdownSchema]


class ModerationEventSchema(BaseModel):
    id: str
    action: str
    reason: Optional[str] = None
    target_user_id: Optional[str] = None
    target_lp_id: Optional[str] = None
    performed_by: Optional[str] = None
    performed_by_username: Optional[str] = None
    performed_by_email: Optional[str] = None
    created_at: str


class ModerationLogListResponse(BaseModel):
    data: List[ModerationEventSchema]


def build_admin_user_summaries(
    supabase: Client,
    *,
    search: Optional[str] = None,
    user_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_ids_filter: Optional[List[str]] = None,
) -> Tuple[List[AdminUserSummarySchema], int]:
    query = supabase.table("users").select("*", count="exact")
    if user_ids_filter:
        query = query.in_("id", user_ids_filter)
    elif search:
        query = query.or_(f"username.ilike.%{search}%,email.ilike.%{search}%")
    if user_type:
        query = query.eq("user_type", user_type)
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    response = query.execute()
    users_raw, total = handle_supabase_response(response, "users query")
    if total is None:
        total = len(users_raw)
    user_ids = [user.get("id") for user in users_raw if user.get("id")]
    if not user_ids:
        summaries = [
            AdminUserSummarySchema(
                id=user.get("id"),
                username=user.get("username", ""),
                email=user.get("email", ""),
                user_type=user.get("user_type", "seller"),
                point_balance=int(user.get("point_balance") or 0),
                created_at=user.get("created_at", now_utc_iso()),
                is_blocked=bool(user.get("is_blocked", False)),
                blocked_reason=user.get("blocked_reason"),
                blocked_at=user.get("blocked_at"),
            )
            for user in users_raw
        ]
        return summaries, total

    lp_counts: Dict[str, int] = defaultdict(int)
    product_counts: Dict[str, int] = defaultdict(int)
    transaction_totals: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "purchased": 0,
        "spent": 0,
        "granted": 0,
        "other": 0,
        "net": 0,
        "latest_activity": None,
        "latest_activity_dt": None,
    })

    lp_response = (
        supabase
        .table("landing_pages")
        .select("seller_id")
        .in_("seller_id", user_ids)
        .execute()
    )
    lp_rows, _ = handle_supabase_response(lp_response, "landing_pages seller lookup")
    for lp in lp_rows:
        seller_id = lp.get("seller_id")
        if seller_id:
            lp_counts[seller_id] += 1

    product_response = (
        supabase
        .table("products")
        .select("seller_id")
        .in_("seller_id", user_ids)
        .execute()
    )
    product_rows, _ = handle_supabase_response(product_response, "products seller lookup")
    for product in product_rows:
        seller_id = product.get("seller_id")
        if seller_id:
            product_counts[seller_id] += 1

    transactions_response = (
        supabase
        .table("point_transactions")
        .select("user_id, transaction_type, amount, created_at")
        .in_("user_id", user_ids)
        .order("created_at", desc=True)
        .limit(5000)
        .execute()
    )
    transaction_rows, _ = handle_supabase_response(transactions_response, "point_transactions lookup")
    for tx in transaction_rows:
        user_id = tx.get("user_id")
        if not user_id:
            continue
        totals = transaction_totals[user_id]
        amount = int(tx.get("amount") or 0)
        tx_type = tx.get("transaction_type")
        dt = parse_iso_datetime(tx.get("created_at"))
        if tx_type == "purchase":
            totals["purchased"] += amount
        elif tx_type == "product_purchase":
            totals["spent"] += abs(amount)
        elif tx_type in {"admin_grant", "manual_adjust"}:
            totals["granted"] += amount
        else:
            totals["other"] += amount
        totals["net"] += amount
        if dt:
            if not totals["latest_activity_dt"] or dt > totals["latest_activity_dt"]:
                totals["latest_activity_dt"] = dt
                totals["latest_activity"] = dt.isoformat()

    summaries: List[AdminUserSummarySchema] = []
    for user in users_raw:
        user_id = user.get("id")
        totals = transaction_totals.get(user_id, {
            "purchased": 0,
            "spent": 0,
            "granted": 0,
            "other": 0,
            "net": 0,
            "latest_activity": None,
        })
        summaries.append(
            AdminUserSummarySchema(
                id=user_id,
                username=user.get("username", ""),
                email=user.get("email", ""),
                user_type=user.get("user_type", "seller"),
                point_balance=int(user.get("point_balance") or 0),
                created_at=user.get("created_at", now_utc_iso()),
                is_blocked=bool(user.get("is_blocked", False)),
                blocked_reason=user.get("blocked_reason"),
                blocked_at=user.get("blocked_at"),
                total_lp_count=lp_counts.get(user_id, 0),
                total_product_count=product_counts.get(user_id, 0),
                total_point_purchased=int(totals.get("purchased") or 0),
                total_point_spent=int(totals.get("spent") or 0),
                total_point_granted=int(totals.get("granted") or 0),
                latest_activity=totals.get("latest_activity"),
            )
        )
    return summaries, total


@router.get("/users", response_model=AdminUserListResponse)
async def list_admin_users(
    search: Optional[str] = Query(None, description="ユーザー名またはメールで検索"),
    user_type: Optional[str] = Query(None, description="ユーザータイプでフィルター"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        summaries, total = build_admin_user_summaries(
            supabase,
            search=search,
            user_type=user_type,
            limit=limit,
            offset=offset,
        )
        return AdminUserListResponse(data=summaries, total=total)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list admin users")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザー一覧の取得に失敗しました: {exc}",
        )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_admin_user_detail(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        summaries, _ = build_admin_user_summaries(
            supabase,
            user_ids_filter=[user_id],
            limit=1,
            offset=0,
        )
        if not summaries:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません",
            )
        summary = summaries[0]

        transactions_response = (
            supabase
            .table("point_transactions")
            .select("id, transaction_type, amount, description, created_at, related_product_id")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        transactions_data = transactions_response.data or []
        product_ids = {
            tx.get("related_product_id")
            for tx in transactions_data
            if tx.get("related_product_id")
        }
        product_titles: Dict[str, str] = {}
        if product_ids:
            products_response = (
                supabase
                .table("products")
                .select("id, title")
                .in_("id", list(product_ids))
                .execute()
            )
            for product in products_response.data or []:
                product_titles[product.get("id")] = product.get("title", "")

        transactions = [
            AdminPointTransactionSchema(
                id=tx.get("id"),
                transaction_type=tx.get("transaction_type", "unknown"),
                amount=int(tx.get("amount") or 0),
                description=tx.get("description"),
                created_at=tx.get("created_at", now_utc_iso()),
                related_product_id=tx.get("related_product_id"),
            )
            for tx in transactions_data
        ]

        purchase_history = [
            AdminUserPurchaseSchema(
                transaction_id=tx.get("id"),
                product_id=tx.get("related_product_id"),
                product_title=product_titles.get(tx.get("related_product_id")),
                amount=int(tx.get("amount") or 0),
                created_at=tx.get("created_at", now_utc_iso()),
                description=tx.get("description"),
            )
            for tx in transactions_data
            if tx.get("transaction_type") == "product_purchase"
        ]

        landing_pages_response = (
            supabase
            .table("landing_pages")
            .select("*")
            .eq("seller_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        landing_page_rows, _ = handle_supabase_response(landing_pages_response, "user landing pages lookup")
        landing_pages = [
            AdminUserLandingPageSchema(
                id=lp.get("id"),
                title=lp.get("title", ""),
                status=lp.get("status", "draft"),
                slug=lp.get("slug", ""),
                total_views=int(lp.get("total_views") or 0),
                total_cta_clicks=int(lp.get("total_cta_clicks") or 0),
                created_at=lp.get("created_at", now_utc_iso()),
                updated_at=lp.get("updated_at", now_utc_iso()),
            )
            for lp in landing_page_rows
        ]

        return AdminUserDetailResponse(
            **summary.model_dump(),
            transactions=transactions,
            landing_pages=landing_pages,
            purchase_history=purchase_history,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch admin user detail")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザー詳細の取得に失敗しました: {exc}",
        )


@router.post("/users/{user_id}/block", response_model=UserActionResponse)
async def block_user(
    user_id: str,
    request: BlockUserRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        user_response = (
            supabase
            .table("users")
            .select("id")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません",
            )
        supabase.table("users").update({
            "is_blocked": True,
            "blocked_reason": request.reason,
            "blocked_at": now_utc_iso(),
        }).eq("id", user_id).execute()
        create_moderation_event(
            supabase,
            action="user_block",
            performed_by=admin.get("id"),
            target_user_id=user_id,
            reason=request.reason,
        )
        return UserActionResponse(user_id=user_id, message="ユーザーをブロックしました")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to block user")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザーブロックに失敗しました: {exc}",
        )


@router.post("/users/{user_id}/unblock", response_model=UserActionResponse)
async def unblock_user(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        supabase.table("users").update({
            "is_blocked": False,
            "blocked_reason": None,
            "blocked_at": None,
        }).eq("id", user_id).execute()
        create_moderation_event(
            supabase,
            action="user_unblock",
            performed_by=admin.get("id"),
            target_user_id=user_id,
        )
        return UserActionResponse(user_id=user_id, message="ユーザーのブロックを解除しました")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to unblock user")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ブロック解除に失敗しました: {exc}",
        )


@router.delete("/users/{user_id}", response_model=UserActionResponse)
async def delete_user(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        supabase.auth.admin.delete_user(user_id)
        create_moderation_event(
            supabase,
            action="user_delete",
            performed_by=admin.get("id"),
            target_user_id=user_id,
        )
        return UserActionResponse(user_id=user_id, message="ユーザーを削除しました")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete user")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザー削除に失敗しました: {exc}",
        )


@router.get("/marketplace/lps", response_model=AdminMarketplaceResponse)
async def list_marketplace_lps(
    status_filter: Optional[str] = Query(None, alias="status", description="対象ステータス"),
    search: Optional[str] = Query(None, description="タイトル検索"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        query = supabase.table("landing_pages").select("*", count="exact")
        if status_filter:
            query = query.eq("status", status_filter)
        else:
            query = query.in_("status", ["draft", "published", "archived"])
        if search:
            query = query.ilike("title", f"%{search}%")
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        lps, total = handle_supabase_response(response, "landing_pages admin list")
        if total is None:
            total = len(lps)
        seller_ids = {lp.get("seller_id") for lp in lps if lp.get("seller_id")}
        seller_map: Dict[str, Dict[str, Any]] = {}
        if seller_ids:
            sellers_response = (
                supabase
                .table("users")
                .select("id, username, email")
                .in_("id", list(seller_ids))
                .execute()
            )
            seller_rows, _ = handle_supabase_response(sellers_response, "users lookup for marketplace")
            for seller in seller_rows:
                seller_map[seller.get("id")] = seller
        lp_ids = [lp.get("id") for lp in lps if lp.get("id")]
        product_counts: Dict[str, int] = defaultdict(int)
        if lp_ids:
            products_response = (
                supabase
                .table("products")
                .select("lp_id")
                .in_("lp_id", lp_ids)
                .execute()
            )
            product_rows, _ = handle_supabase_response(products_response, "products lookup for marketplace")
            for product in product_rows:
                lp_id = product.get("lp_id")
                if lp_id:
                    product_counts[lp_id] += 1
        items = [
            AdminMarketplaceItemSchema(
                id=lp.get("id"),
                title=lp.get("title", ""),
                slug=lp.get("slug", ""),
                status=lp.get("status", "draft"),
                seller_id=lp.get("seller_id", ""),
                seller_username=seller_map.get(lp.get("seller_id"), {}).get("username", ""),
                seller_email=seller_map.get(lp.get("seller_id"), {}).get("email", ""),
                total_views=int(lp.get("total_views") or 0),
                total_cta_clicks=int(lp.get("total_cta_clicks") or 0),
                created_at=lp.get("created_at", now_utc_iso()),
                updated_at=lp.get("updated_at", now_utc_iso()),
                product_count=product_counts.get(lp.get("id"), 0),
            )
            for lp in lps
        ]
        return AdminMarketplaceResponse(data=items, total=total)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list marketplace LPs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"マーケット情報の取得に失敗しました: {exc}",
        )


@router.post("/marketplace/lps/{lp_id}/status", response_model=UserActionResponse)
async def update_lp_status(
    lp_id: str,
    request: LPStatusUpdateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        lp_response = (
            supabase
            .table("landing_pages")
            .select("id, seller_id, status")
            .eq("id", lp_id)
            .single()
            .execute()
        )
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません",
            )
        supabase.table("landing_pages").update({
            "status": request.status,
            "updated_at": now_utc_iso(),
        }).eq("id", lp_id).execute()
        create_moderation_event(
            supabase,
            action=f"lp_status_{request.status}",
            performed_by=admin.get("id"),
            target_user_id=lp_response.data.get("seller_id"),
            target_lp_id=lp_id,
            reason=request.reason,
        )
        return UserActionResponse(
            user_id=lp_response.data.get("seller_id"),
            message="LPステータスを更新しました",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update LP status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LPステータスの更新に失敗しました: {exc}",
        )


@router.get("/analytics/points", response_model=PointAnalyticsResponse)
async def get_point_analytics(
    limit_days: int = Query(120, ge=7, le=365, description="集計対象の日数"),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        transactions_response = (
            supabase
            .table("point_transactions")
            .select("transaction_type, amount, created_at")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        transactions = transactions_response.data or []
        cutoff = datetime.now(timezone.utc) - timedelta(days=limit_days)
        totals = {"purchased": 0, "spent": 0, "granted": 0, "other": 0, "net": 0}
        daily: Dict[str, Dict[str, int]] = defaultdict(lambda: {"purchased": 0, "spent": 0, "granted": 0, "other": 0, "net": 0})
        monthly: Dict[str, Dict[str, int]] = defaultdict(lambda: {"purchased": 0, "spent": 0, "granted": 0, "other": 0, "net": 0})
        for tx in transactions:
            dt = parse_iso_datetime(tx.get("created_at"))
            if not dt:
                continue
            amount = int(tx.get("amount") or 0)
            tx_type = tx.get("transaction_type")
            bucket_daily = dt.date().isoformat()
            bucket_monthly = dt.strftime("%Y-%m")
            if tx_type == "purchase":
                totals["purchased"] += amount
                daily[bucket_daily]["purchased"] += amount
                monthly[bucket_monthly]["purchased"] += amount
            elif tx_type == "product_purchase":
                spent_value = abs(amount)
                totals["spent"] += spent_value
                daily[bucket_daily]["spent"] += spent_value
                monthly[bucket_monthly]["spent"] += spent_value
                amount = -spent_value
            elif tx_type in {"admin_grant", "manual_adjust"}:
                totals["granted"] += amount
                daily[bucket_daily]["granted"] += amount
                monthly[bucket_monthly]["granted"] += amount
            else:
                totals["other"] += amount
                daily[bucket_daily]["other"] += amount
                monthly[bucket_monthly]["other"] += amount
            totals["net"] += amount
            daily[bucket_daily]["net"] += amount
            monthly[bucket_monthly]["net"] += amount
        daily_rows = [
            PointAnalyticsBreakdownSchema(
                label=label,
                purchased=values["purchased"],
                spent=values["spent"],
                granted=values["granted"],
                other=values["other"],
                net=values["net"],
            )
            for label, values in sorted(daily.items(), key=lambda item: item[0], reverse=True)
            if parse_iso_datetime(f"{label}T00:00:00+00:00") and parse_iso_datetime(f"{label}T00:00:00+00:00") >= cutoff
        ]
        monthly_rows = [
            PointAnalyticsBreakdownSchema(
                label=label,
                purchased=values["purchased"],
                spent=values["spent"],
                granted=values["granted"],
                other=values["other"],
                net=values["net"],
            )
            for label, values in sorted(monthly.items(), key=lambda item: item[0], reverse=True)
        ]
        return PointAnalyticsResponse(
            totals=PointAnalyticsTotalsSchema(**totals),
            daily=daily_rows,
            monthly=monthly_rows,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to build point analytics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ポイント分析の取得に失敗しました: {exc}",
        )


@router.get("/moderation/logs", response_model=ModerationLogListResponse)
async def get_moderation_logs(
    limit: int = Query(100, ge=1, le=500),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        response = (
            supabase
            .table("moderation_events")
            .select("id, action, reason, target_user_id, target_lp_id, performed_by, created_at")
            .order("created_at", desc=True)
            .range(0, limit - 1)
            .execute()
        )
        events = response.data or []
        performer_ids = {
            event.get("performed_by")
            for event in events
            if event.get("performed_by")
        }
        performer_map: Dict[str, Dict[str, Any]] = {}
        if performer_ids:
            performers_response = (
                supabase
                .table("users")
                .select("id, username, email")
                .in_("id", list(performer_ids))
                .execute()
            )
            for performer in performers_response.data or []:
                performer_map[performer.get("id")] = performer
        log_rows = [
            ModerationEventSchema(
                id=event.get("id"),
                action=event.get("action", ""),
                reason=event.get("reason"),
                target_user_id=event.get("target_user_id"),
                target_lp_id=event.get("target_lp_id"),
                performed_by=event.get("performed_by"),
                performed_by_username=performer_map.get(event.get("performed_by"), {}).get("username"),
                performed_by_email=performer_map.get(event.get("performed_by"), {}).get("email"),
                created_at=event.get("created_at", now_utc_iso()),
            )
            for event in events
        ]
        return ModerationLogListResponse(data=log_rows)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch moderation logs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"モデレーションログの取得に失敗しました: {exc}",
        )


@router.post("/points/grant", response_model=GrantPointsResponse)
async def grant_points(
    data: GrantPointsRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        user_response = (
            supabase
            .table("users")
            .select("username, point_balance")
            .eq("id", data.user_id)
            .single()
            .execute()
        )
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたユーザーが見つかりません",
            )
        user = user_response.data
        current_balance = int(user.get("point_balance") or 0)
        new_balance = current_balance + data.amount
        if new_balance < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ポイント残高がマイナスになります（現在: {current_balance}、変更: {data.amount}）",
            )
        supabase.table("users").update({"point_balance": new_balance}).eq("id", data.user_id).execute()
        transaction_response = (
            supabase
            .table("point_transactions")
            .insert({
                "user_id": data.user_id,
                "transaction_type": "admin_grant",
                "amount": data.amount,
                "description": f"{data.description} (管理者: {admin.get('username', 'admin')})",
            })
            .execute()
        )
        if not transaction_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="トランザクション記録に失敗しました",
            )
        transaction = transaction_response.data[0]
        create_moderation_event(
            supabase,
            action="user_points_grant",
            performed_by=admin.get("id"),
            target_user_id=data.user_id,
            reason=data.description,
        )
        return GrantPointsResponse(
            transaction_id=transaction.get("id"),
            user_id=data.user_id,
            username=user.get("username", ""),
            amount=data.amount,
            new_balance=new_balance,
            description=data.description or "",
            granted_at=transaction.get("created_at", now_utc_iso()),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to grant points")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ポイント付与エラー: {exc}",
        )


@router.get("/users/search", response_model=UserListResponse)
async def search_users(
    query: Optional[str] = Query(None, description="検索キーワード"),
    user_type: Optional[str] = Query(None, description="ユーザータイプ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    summaries, total = build_admin_user_summaries(
        get_supabase(),
        search=query,
        user_type=user_type,
        limit=limit,
        offset=offset,
    )
    users = [
        UserSearchResponse(
            id=item.id,
            username=item.username,
            email=item.email,
            user_type=item.user_type,
            point_balance=item.point_balance,
            created_at=item.created_at,
        )
        for item in summaries
    ]
    return UserListResponse(data=users, total=total)
