
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from supabase import Client, create_client

from app.config import settings
from app.services.risk_scoring import calculate_note_risk, calculate_salon_risk
from app.utils.auth import decode_access_token

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

ADMIN_EMAILS = {
    "goldbenchan@gmail.com",
    "kusanokiyoshi1@gmail.com",
}
EXCLUDED_EMAILS = {
    "seller1@example.com",
    "testuser1234@example.com",
    "factorybot@example.com",
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


def normalize_published_at(value: Optional[str]) -> str:
    if not value:
        return now_utc_iso()
    dt = parse_iso_datetime(value)
    if not dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="公開日時の形式が正しくありません",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def get_current_user(credentials: HTTPAuthorizationCredentials) -> dict:
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
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
    target_note_id: Optional[str] = None,
    target_salon_id: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    event = {
        "action": action,
        "performed_by": performed_by,
        "target_user_id": target_user_id,
        "target_lp_id": target_lp_id,
        "target_note_id": target_note_id,
        "target_salon_id": target_salon_id,
        "reason": reason,
        "metadata": metadata or {},
        "created_at": now_utc_iso(),
    }
    try:
        supabase.table("moderation_events").insert(event).execute()
    except Exception as exc:  # pragma: no cover - logging only
        logger.warning("Failed to record moderation event: %s", exc)


def handle_supabase_response(
    response,
    context: str,
    *,
    raise_on_error: bool = True,
) -> Tuple[Any, Optional[int]]:
    error = getattr(response, "error", None)
    if error:
        message = getattr(error, "message", None) or str(error)
        logger.error("Supabase error in %s: %s", context, message)
        if raise_on_error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{context}: {message}",
            )
        return [], None
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
    line_connected: bool = False
    line_display_name: Optional[str] = None
    line_bonus_awarded: bool = False
    total_note_count: int = 0
    published_note_count: int = 0
    latest_note_title: Optional[str] = None
    latest_note_updated_at: Optional[str] = None


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


class AdminUserNoteSchema(BaseModel):
    id: str
    title: str
    status: str
    slug: str
    is_paid: bool
    price_points: int
    created_at: str
    updated_at: str
    published_at: Optional[str] = None
    total_purchases: int = 0
    categories: List[str] = Field(default_factory=list)


class AdminUserDetailResponse(AdminUserSummarySchema):
    transactions: List[AdminPointTransactionSchema]
    landing_pages: List[AdminUserLandingPageSchema]
    purchase_history: List[AdminUserPurchaseSchema]
    notes: List[AdminUserNoteSchema]


class UserActionResponse(BaseModel):
    success: bool = True
    user_id: Optional[str]
    message: str
    note_id: Optional[str] = None
    salon_id: Optional[str] = None


class BlockUserRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=400)


class NoteActionRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class LPStatusUpdateRequest(BaseModel):
    status: Literal['published', 'archived']
    reason: Optional[str] = Field(default=None, max_length=500)


class FeaturedItemToggleRequest(BaseModel):
    entity_type: Literal['product', 'note', 'salon']
    entity_id: str
    is_featured: bool


class FeaturedToggleResponse(BaseModel):
    entity_type: Literal['product', 'note', 'salon']
    entity_id: str
    title: str
    is_featured: bool


class FeaturedProductSummary(BaseModel):
    id: str
    title: str
    lp_slug: Optional[str] = None
    seller_username: Optional[str] = None
    is_available: bool
    is_featured: bool
    created_at: Optional[str] = None


class FeaturedProductListResponse(BaseModel):
    data: List[FeaturedProductSummary]
    total: int


class FeaturedNoteSummary(BaseModel):
    id: str
    title: str
    slug: Optional[str] = None
    author_username: Optional[str] = None
    status: Optional[str] = None
    is_featured: bool
    published_at: Optional[str] = None


class FeaturedNoteListResponse(BaseModel):
    data: List[FeaturedNoteSummary]
    total: int


class FeaturedSalonSummary(BaseModel):
    id: str
    title: str
    owner_username: Optional[str] = None
    is_active: bool
    is_featured: bool
    created_at: Optional[str] = None


class FeaturedSalonListResponse(BaseModel):
    data: List[FeaturedSalonSummary]
    total: int


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


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    summary: str = Field(..., max_length=255)
    body: str = Field(..., max_length=10000)
    published_at: Optional[str] = None
    is_published: bool = True
    highlight: bool = False


class AnnouncementUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=255)
    body: Optional[str] = Field(default=None, max_length=10000)
    published_at: Optional[str] = None
    is_published: Optional[bool] = None
    highlight: Optional[bool] = None


class AdminAnnouncementSchema(BaseModel):
    id: str
    title: str
    summary: str
    body: str
    is_published: bool
    highlight: bool
    published_at: str
    created_at: str
    updated_at: str
    created_by: Optional[str] = None
    created_by_email: Optional[str] = None
    created_by_username: Optional[str] = None


class AdminAnnouncementListResponse(BaseModel):
    data: List[AdminAnnouncementSchema]
    total: int


class NoteModerationItemSchema(BaseModel):
    id: str
    title: str
    status: str
    author_id: str
    author_username: Optional[str] = None
    author_email: Optional[str] = None
    author_user_type: Optional[str] = None
    price_points: Optional[int] = None
    price_jpy: Optional[int] = None
    is_paid: bool
    allow_point_purchase: bool
    allow_jpy_purchase: bool
    total_purchases: int
    total_shares: int
    suspicious_shares: int
    total_refunds: int
    risk_score: float
    risk_indicators: List[str]
    created_at: str
    updated_at: str
    published_at: Optional[str] = None
    categories: List[str] = Field(default_factory=list)


class NoteModerationListResponse(BaseModel):
    data: List[NoteModerationItemSchema]
    total: int
    limit: int
    offset: int


class NoteModerationDetailSchema(NoteModerationItemSchema):
    excerpt: Optional[str] = None
    content_blocks: Any
    official_share_tweet_url: Optional[str] = None
    official_share_x_username: Optional[str] = None


class SalonModerationItemSchema(BaseModel):
    id: str
    title: str
    status: str
    is_active: bool
    owner_id: str
    owner_username: Optional[str] = None
    owner_email: Optional[str] = None
    monthly_price_jpy: Optional[int] = None
    allow_point_subscription: bool
    allow_jpy_subscription: bool
    active_members: int
    pending_members: int
    canceled_members: int
    total_members: int
    risk_score: float
    risk_indicators: List[str]
    created_at: str
    updated_at: str


class SalonModerationListResponse(BaseModel):
    data: List[SalonModerationItemSchema]
    total: int
    limit: int
    offset: int


class SalonMemberModerationSchema(BaseModel):
    id: str
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    status: str
    joined_at: Optional[str] = None
    last_charged_at: Optional[str] = None
    next_charge_at: Optional[str] = None
    canceled_at: Optional[str] = None


class SalonModerationDetailSchema(SalonModerationItemSchema):
    description: Optional[str] = None
    moderation_notes: Optional[str] = None
    owner_user_type: Optional[str] = None
    members: List[SalonMemberModerationSchema] = Field(default_factory=list)
    announcements_count: int = 0
    events_count: int = 0
    posts_count: int = 0


class SalonStatusUpdateRequest(BaseModel):
    status: Literal["pending", "approved", "rejected", "suspended"]
    reason: Optional[str] = None
    moderation_notes: Optional[str] = None


class SalonMemberActionRequest(BaseModel):
    action: Literal["approve", "cancel"]
    reason: Optional[str] = None


class MaintenanceModeSchema(BaseModel):
    id: str
    scope: str
    status: str
    title: str
    message: Optional[str] = None
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    activated_at: Optional[str] = None
    deactivated_at: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class MaintenanceModeListResponse(BaseModel):
    data: List[MaintenanceModeSchema]


class MaintenanceModeCreateRequest(BaseModel):
    scope: Literal["global", "lp", "note", "salon", "points", "products", "ai", "payments"]
    title: str = Field(..., max_length=120)
    message: Optional[str] = Field(None, max_length=2000)
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None


class MaintenanceModeStatusUpdateRequest(BaseModel):
    status: Literal["scheduled", "active", "completed", "cancelled"]
    message: Optional[str] = None


class SystemStatusCheckSchema(BaseModel):
    id: str
    component: str
    status: str
    response_time_ms: Optional[int] = None
    message: Optional[str] = None
    checked_at: str
    created_by: Optional[str] = None


class SystemStatusCheckListResponse(BaseModel):
    data: List[SystemStatusCheckSchema]


class SystemStatusCheckCreateRequest(BaseModel):
    component: str = Field(..., max_length=80)
    status: Literal["healthy", "degraded", "down"]
    response_time_ms: Optional[int] = Field(None, ge=0)
    message: Optional[str] = Field(None, max_length=2000)


def build_admin_announcement(row: Dict[str, Any]) -> AdminAnnouncementSchema:
    return AdminAnnouncementSchema(
        id=str(row.get("id")),
        title=row.get("title", ""),
        summary=row.get("summary", ""),
        body=row.get("body", ""),
        is_published=bool(row.get("is_published", True)),
        highlight=bool(row.get("highlight", False)),
        published_at=row.get("published_at") or row.get("created_at") or now_utc_iso(),
        created_at=row.get("created_at") or now_utc_iso(),
        updated_at=row.get("updated_at") or row.get("created_at") or now_utc_iso(),
        created_by=row.get("created_by"),
        created_by_email=row.get("created_by_email"),
        created_by_username=row.get("created_by_username"),
    )


def build_maintenance_mode(row: Dict[str, Any]) -> MaintenanceModeSchema:
    return MaintenanceModeSchema(
        id=str(row.get("id")),
        scope=row.get("scope", "global"),
        status=row.get("status", "scheduled"),
        title=row.get("title", ""),
        message=row.get("message"),
        planned_start=row.get("planned_start"),
        planned_end=row.get("planned_end"),
        activated_at=row.get("activated_at"),
        deactivated_at=row.get("deactivated_at"),
        created_by=row.get("created_by"),
        created_at=row.get("created_at", now_utc_iso()),
        updated_at=row.get("updated_at", now_utc_iso()),
    )


def build_system_status_check(row: Dict[str, Any]) -> SystemStatusCheckSchema:
    return SystemStatusCheckSchema(
        id=str(row.get("id")),
        component=row.get("component", "unknown"),
        status=row.get("status", "healthy"),
        response_time_ms=row.get("response_time_ms"),
        message=row.get("message"),
        checked_at=row.get("checked_at", now_utc_iso()),
        created_by=row.get("created_by"),
    )


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
    if not user_ids_filter:
        users_raw = [user for user in users_raw if user.get("email") not in EXCLUDED_EMAILS]
    if not user_ids_filter:
        users_raw = [user for user in users_raw if user.get("email") not in EXCLUDED_EMAILS]
    if total is None or not user_ids_filter:
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
                line_connected=False,
                line_display_name=None,
                line_bonus_awarded=False,
            )
            for user in users_raw
        ]
        return summaries, total

    lp_counts: Dict[str, int] = defaultdict(int)
    product_counts: Dict[str, int] = defaultdict(int)
    line_connections: Dict[str, Dict[str, Any]] = {}
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

    note_counts: Dict[str, int] = defaultdict(int)
    published_note_counts: Dict[str, int] = defaultdict(int)
    note_latest_title: Dict[str, str] = {}
    note_latest_dt: Dict[str, datetime] = {}

    if user_ids:
        notes_response = (
            supabase
            .table("notes")
            .select("author_id,status,title,updated_at,created_at")
            .in_("author_id", user_ids)
            .execute()
        )
        note_rows, _ = handle_supabase_response(notes_response, "notes author lookup", raise_on_error=False)
        for note in note_rows:
            author_id = note.get("author_id")
            if not author_id:
                continue
            note_counts[author_id] += 1
            if note.get("status") == "published":
                published_note_counts[author_id] += 1
            updated_raw = note.get("updated_at") or note.get("created_at")
            updated_dt = parse_iso_datetime(updated_raw)
            if updated_dt:
                current_dt = note_latest_dt.get(author_id)
                if not current_dt or updated_dt > current_dt:
                    note_latest_dt[author_id] = updated_dt
                    note_latest_title[author_id] = note.get("title", "")

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

    # LINE連携情報を取得
    try:
        line_response = (
            supabase
            .table("line_connections")
            .select("user_id, display_name, bonus_awarded")
            .in_("user_id", user_ids)
            .execute()
        )
        line_rows, _ = handle_supabase_response(line_response, "line_connections lookup", raise_on_error=False)
        for line_conn in line_rows:
            user_id = line_conn.get("user_id")
            if user_id:
                line_connections[user_id] = {
                    "connected": True,
                    "display_name": line_conn.get("display_name"),
                    "bonus_awarded": bool(line_conn.get("bonus_awarded", False))
                }
    except Exception as e:
        logger.warning(f"Failed to fetch LINE connections: {e}")

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
        line_info = line_connections.get(user_id, {})
        latest_note_dt = note_latest_dt.get(user_id)
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
                line_connected=line_info.get("connected", False),
                line_display_name=line_info.get("display_name"),
                line_bonus_awarded=line_info.get("bonus_awarded", False),
                total_note_count=note_counts.get(user_id, 0),
                published_note_count=published_note_counts.get(user_id, 0),
                latest_note_title=note_latest_title.get(user_id),
                latest_note_updated_at=latest_note_dt.isoformat() if latest_note_dt else None,
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

        notes_response = (
            supabase
            .table("notes")
            .select("id,title,slug,status,is_paid,price_points,created_at,updated_at,published_at,categories")
            .eq("author_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        note_rows, _ = handle_supabase_response(notes_response, "admin user notes lookup", raise_on_error=False)
        note_ids = [note.get("id") for note in note_rows if note.get("id")]
        note_purchase_counts: Dict[str, int] = defaultdict(int)
        if note_ids:
            purchases_response = (
                supabase
                .table("note_purchases")
                .select("note_id")
                .in_("note_id", note_ids)
                .execute()
            )
            purchase_rows, _ = handle_supabase_response(purchases_response, "admin note purchase lookup", raise_on_error=False)
            for purchase in purchase_rows:
                note_id = purchase.get("note_id")
                if note_id:
                    note_purchase_counts[note_id] += 1

        notes = [
            AdminUserNoteSchema(
                id=note.get("id"),
                title=note.get("title", ""),
                status=note.get("status", "draft"),
                slug=note.get("slug", ""),
                is_paid=bool(note.get("is_paid", False)),
                price_points=int(note.get("price_points") or 0),
                created_at=note.get("created_at", now_utc_iso()),
                updated_at=note.get("updated_at", now_utc_iso()),
                published_at=note.get("published_at"),
                total_purchases=note_purchase_counts.get(note.get("id"), 0),
                categories=list(note.get("categories") or []),
            )
            for note in note_rows
            if note.get("id")
        ]

        return AdminUserDetailResponse(
            **summary.model_dump(),
            transactions=transactions,
            landing_pages=landing_pages,
            purchase_history=purchase_history,
            notes=notes,
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


@router.post("/users/{user_id}/notes/{note_id}/unpublish", response_model=UserActionResponse)
async def admin_unpublish_note(
    user_id: str,
    note_id: str,
    request: NoteActionRequest | None = None,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        note_response = (
            supabase
            .table("notes")
            .select("id,author_id,status,title")
            .eq("id", note_id)
            .single()
            .execute()
        )
        note = getattr(note_response, "data", None)
        if not note:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOTEが見つかりません")
        if note.get("author_id") != user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定したユーザーのNOTEではありません")
        if note.get("status") == "draft":
            return UserActionResponse(user_id=user_id, note_id=note_id, message="NOTEは既に下書きです")

        supabase.table("notes").update({
            "status": "draft",
            "published_at": None,
            "updated_at": now_utc_iso(),
        }).eq("id", note_id).execute()

        reason_text = request.reason if request and request.reason else f"note:{note_id} ({note.get('title')})"
        create_moderation_event(
            supabase,
            action="note_unpublish",
            performed_by=admin.get("id"),
            target_user_id=user_id,
            reason=reason_text,
        )

        return UserActionResponse(user_id=user_id, note_id=note_id, message="NOTEを非公開にしました")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to unpublish note")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NOTEの非公開化に失敗しました: {exc}",
        )


@router.post("/users/{user_id}/notes/{note_id}/delete", response_model=UserActionResponse)
async def admin_delete_note(
    user_id: str,
    note_id: str,
    request: NoteActionRequest | None = None,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        note_response = (
            supabase
            .table("notes")
            .select("id,author_id,title")
            .eq("id", note_id)
            .single()
            .execute()
        )
        note = getattr(note_response, "data", None)
        if not note:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOTEが見つかりません")
        if note.get("author_id") != user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定したユーザーのNOTEではありません")

        supabase.table("notes").delete().eq("id", note_id).execute()

        reason_text = request.reason if request and request.reason else f"note:{note_id} ({note.get('title')})"
        create_moderation_event(
            supabase,
            action="note_delete",
            performed_by=admin.get("id"),
            target_user_id=user_id,
            reason=reason_text,
        )

        return UserActionResponse(user_id=user_id, note_id=note_id, message="NOTEを削除しました")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete note")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NOTEの削除に失敗しました: {exc}",
        )


@router.get("/notes/moderation", response_model=NoteModerationListResponse)
async def list_notes_for_moderation(
    status: Optional[str] = Query(None, description="対象ステータス (draft/published)"),
    search: Optional[str] = Query(None, description="タイトル検索"),
    min_risk: Optional[float] = Query(None, ge=0, description="最小リスクスコア"),
    max_risk: Optional[float] = Query(None, ge=0, description="最大リスクスコア"),
    only_suspicious: bool = Query(False, description="疑わしいシェアを含むNOTEのみ返す"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        select_fields = (
            "id,author_id,title,status,is_paid,price_points,price_jpy,allow_point_purchase,"
            "allow_jpy_purchase,created_at,updated_at,published_at,categories"
        )
        query = supabase.table("notes").select(select_fields, count="exact")
        if status:
            query = query.eq("status", status)
        if search:
            query = query.ilike("title", f"%{search}%")
        notes_response = query.order("updated_at", desc=True).range(offset, offset + limit - 1).execute()
        note_rows, total = handle_supabase_response(notes_response, "admin note moderation list")

        note_ids = [note.get("id") for note in note_rows if note.get("id")]
        author_ids: Set[str] = {note.get("author_id") for note in note_rows if note.get("author_id")}

        purchase_counts: Dict[str, int] = defaultdict(int)
        refund_counts: Dict[str, int] = defaultdict(int)
        share_counts: Dict[str, int] = defaultdict(int)
        suspicious_share_counts: Dict[str, int] = defaultdict(int)

        if note_ids:
            purchases_response = (
                supabase
                .table("note_purchases")
                .select("note_id")
                .in_("note_id", note_ids)
                .execute()
            )
            purchase_rows, _ = handle_supabase_response(purchases_response, "admin note purchase lookup", raise_on_error=False)
            for purchase in purchase_rows:
                note_id = purchase.get("note_id")
                if note_id:
                    purchase_counts[note_id] += 1

            transactions_response = (
                supabase
                .table("point_transactions")
                .select("related_note_id, transaction_type")
                .in_("related_note_id", note_ids)
                .execute()
            )
            transaction_rows, _ = handle_supabase_response(transactions_response, "admin note transaction lookup", raise_on_error=False)
            for tx in transaction_rows:
                note_id = tx.get("related_note_id")
                tx_type = tx.get("transaction_type")
                if note_id and tx_type in {"refund", "chargeback", "note_refund"}:
                    refund_counts[note_id] += 1

            shares_response = (
                supabase
                .table("note_shares")
                .select("note_id,is_suspicious")
                .in_("note_id", note_ids)
                .execute()
            )
            share_rows, _ = handle_supabase_response(shares_response, "admin note share lookup", raise_on_error=False)
            for share in share_rows:
                note_id = share.get("note_id")
                if note_id:
                    share_counts[note_id] += 1
                    if share.get("is_suspicious"):
                        suspicious_share_counts[note_id] += 1

        user_map: Dict[str, Dict[str, Any]] = {}
        if author_ids:
            users_response = (
                supabase
                .table("users")
                .select("id,username,email,user_type")
                .in_("id", list(author_ids))
                .execute()
            )
            user_rows, _ = handle_supabase_response(users_response, "admin note author lookup", raise_on_error=False)
            for row in user_rows:
                if row.get("id"):
                    user_map[row["id"]] = row

        items: List[NoteModerationItemSchema] = []
        for note in note_rows:
            note_id = note.get("id")
            author_id = note.get("author_id")
            if not note_id or not author_id:
                continue
            total_purchases = purchase_counts.get(note_id, 0)
            total_refunds = refund_counts.get(note_id, 0)
            total_shares = share_counts.get(note_id, 0)
            suspicious_shares = suspicious_share_counts.get(note_id, 0)
            risk_result = calculate_note_risk(
                note,
                total_purchases=total_purchases,
                suspicious_shares=suspicious_shares,
                total_refunds=total_refunds,
            )

            if min_risk is not None and risk_result.score < min_risk:
                continue
            if max_risk is not None and risk_result.score > max_risk:
                continue
            if only_suspicious and suspicious_shares == 0:
                continue

            author = user_map.get(author_id, {})
            items.append(NoteModerationItemSchema(
                id=note_id,
                title=note.get("title", ""),
                status=note.get("status", "draft"),
                author_id=author_id,
                author_username=author.get("username"),
                author_email=author.get("email"),
                author_user_type=author.get("user_type"),
                price_points=int(note.get("price_points") or 0) if note.get("price_points") is not None else None,
                price_jpy=int(note.get("price_jpy") or 0) if note.get("price_jpy") is not None else None,
                is_paid=bool(note.get("is_paid", False)),
                allow_point_purchase=bool(note.get("allow_point_purchase", True)),
                allow_jpy_purchase=bool(note.get("allow_jpy_purchase", False)),
                total_purchases=total_purchases,
                total_shares=total_shares,
                suspicious_shares=suspicious_shares,
                total_refunds=total_refunds,
                risk_score=risk_result.score,
                risk_indicators=risk_result.indicators,
                created_at=note.get("created_at", now_utc_iso()),
                updated_at=note.get("updated_at", now_utc_iso()),
                published_at=note.get("published_at"),
                categories=list(note.get("categories") or []),
            ))

        return NoteModerationListResponse(
            data=items,
            total=len(items) if total is None else min(len(items), total),
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list notes for moderation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NOTEモデレーション一覧の取得に失敗しました: {exc}",
        )


@router.get("/notes/{note_id}/moderation", response_model=NoteModerationDetailSchema)
async def get_note_moderation_detail(
    note_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        note_response = (
            supabase
            .table("notes")
            .select(
                "id,author_id,title,status,is_paid,price_points,price_jpy,allow_point_purchase,allow_jpy_purchase,"
                "created_at,updated_at,published_at,categories,excerpt,content_blocks,official_share_tweet_url,official_share_x_username"
            )
            .eq("id", note_id)
            .single()
            .execute()
        )
        note = getattr(note_response, "data", None)
        if not note:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOTEが見つかりません")

        author_id = note.get("author_id")
        author: Dict[str, Any] = {}
        if author_id:
            author_response = (
                supabase
                .table("users")
                .select("id,username,email,user_type")
                .eq("id", author_id)
                .single()
                .execute()
            )
            author = getattr(author_response, "data", {}) or {}

        total_purchases = 0
        purchases_response = (
            supabase
            .table("note_purchases")
            .select("note_id")
            .eq("note_id", note_id)
            .execute()
        )
        purchase_rows, _ = handle_supabase_response(purchases_response, "note moderation purchases", raise_on_error=False)
        total_purchases = len([row for row in purchase_rows if row.get("note_id")])

        share_rows = []
        shares_response = (
            supabase
            .table("note_shares")
            .select("note_id,is_suspicious")
            .eq("note_id", note_id)
            .execute()
        )
        share_rows, _ = handle_supabase_response(shares_response, "note moderation shares", raise_on_error=False)
        total_shares = len([row for row in share_rows if row.get("note_id")])
        suspicious_shares = len([row for row in share_rows if row.get("is_suspicious")])

        refund_rows = []
        refunds_response = (
            supabase
            .table("point_transactions")
            .select("related_note_id, transaction_type")
            .eq("related_note_id", note_id)
            .execute()
        )
        refund_rows, _ = handle_supabase_response(refunds_response, "note moderation refunds", raise_on_error=False)
        total_refunds = len([
            row
            for row in refund_rows
            if row.get("transaction_type") in {"refund", "chargeback", "note_refund"}
        ])

        risk_result = calculate_note_risk(
            note,
            total_purchases=total_purchases,
            suspicious_shares=suspicious_shares,
            total_refunds=total_refunds,
        )

        return NoteModerationDetailSchema(
            id=note_id,
            title=note.get("title", ""),
            status=note.get("status", "draft"),
            author_id=author_id or "",
            author_username=author.get("username"),
            author_email=author.get("email"),
            author_user_type=author.get("user_type"),
            price_points=int(note.get("price_points") or 0) if note.get("price_points") is not None else None,
            price_jpy=int(note.get("price_jpy") or 0) if note.get("price_jpy") is not None else None,
            is_paid=bool(note.get("is_paid", False)),
            allow_point_purchase=bool(note.get("allow_point_purchase", True)),
            allow_jpy_purchase=bool(note.get("allow_jpy_purchase", False)),
            total_purchases=total_purchases,
            total_shares=total_shares,
            suspicious_shares=suspicious_shares,
            total_refunds=total_refunds,
            risk_score=risk_result.score,
            risk_indicators=risk_result.indicators,
            created_at=note.get("created_at", now_utc_iso()),
            updated_at=note.get("updated_at", now_utc_iso()),
            published_at=note.get("published_at"),
            categories=list(note.get("categories") or []),
            excerpt=note.get("excerpt"),
            content_blocks=note.get("content_blocks") or [],
            official_share_tweet_url=note.get("official_share_tweet_url"),
            official_share_x_username=note.get("official_share_x_username"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get note moderation detail")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NOTEモデレーション詳細の取得に失敗しました: {exc}",
        )


@router.get("/salons/moderation", response_model=SalonModerationListResponse)
async def list_salons_for_moderation(
    status: Optional[str] = Query(None, description="対象ステータス (pending/approved/rejected/suspended)"),
    search: Optional[str] = Query(None, description="サロンタイトル検索"),
    min_risk: Optional[float] = Query(None, ge=0, description="最小リスクスコア"),
    max_risk: Optional[float] = Query(None, ge=0, description="最大リスクスコア"),
    only_flagged: bool = Query(False, description="審査待ちまたは停止中のみ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        select_fields = (
            "id,owner_id,title,description,status,is_active,monthly_price_jpy,allow_point_subscription,"
            "allow_jpy_subscription,moderation_notes,created_at,updated_at"
        )
        query = supabase.table("salons").select(select_fields, count="exact")
        if status:
            query = query.eq("status", status)
        if search:
            query = query.ilike("title", f"%{search}%")
        response = query.order("updated_at", desc=True).range(offset, offset + limit - 1).execute()
        salon_rows, total = handle_supabase_response(response, "admin salon moderation list")

        salon_ids = [row.get("id") for row in salon_rows if row.get("id")]
        owner_ids: Set[str] = {row.get("owner_id") for row in salon_rows if row.get("owner_id")}

        membership_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        if salon_ids:
            memberships_response = (
                supabase
                .table("salon_memberships")
                .select("salon_id,status")
                .in_("salon_id", salon_ids)
                .execute()
            )
            membership_rows, _ = handle_supabase_response(
                memberships_response,
                "admin salon membership lookup",
                raise_on_error=False,
            )
            for membership in membership_rows:
                salon_id = membership.get("salon_id")
                if not salon_id:
                    continue
                status_value = (membership.get("status") or "").upper()
                membership_counts[salon_id][status_value] += 1

        user_map: Dict[str, Dict[str, Any]] = {}
        if owner_ids:
            owners_response = (
                supabase
                .table("users")
                .select("id,username,email,user_type")
                .in_("id", list(owner_ids))
                .execute()
            )
            owner_rows, _ = handle_supabase_response(
                owners_response,
                "admin salon owner lookup",
                raise_on_error=False,
            )
            for row in owner_rows:
                if row.get("id"):
                    user_map[row["id"]] = row

        items: List[SalonModerationItemSchema] = []
        for salon in salon_rows:
            salon_id = salon.get("id")
            if not salon_id:
                continue

            counts = membership_counts.get(salon_id, {})
            active_members = counts.get("ACTIVE", 0)
            pending_members = counts.get("PENDING", 0) + counts.get("WAITING", 0)
            canceled_members = counts.get("CANCELED", 0) + counts.get("CANCELLED", 0)
            total_members = sum(counts.values()) if counts else active_members + pending_members + canceled_members

            risk_result = calculate_salon_risk(
                salon,
                active_members=active_members,
                pending_members=pending_members,
                canceled_members=canceled_members,
                monthly_price_jpy=salon.get("monthly_price_jpy"),
                refunds=0,
            )

            if min_risk is not None and risk_result.score < min_risk:
                continue
            if max_risk is not None and risk_result.score > max_risk:
                continue
            if only_flagged and (salon.get("status") not in {"pending", "suspended"}):
                continue

            owner = user_map.get(salon.get("owner_id"), {})

            items.append(SalonModerationItemSchema(
                id=salon_id,
                title=salon.get("title", ""),
                status=salon.get("status", "approved"),
                is_active=bool(salon.get("is_active", True)),
                owner_id=salon.get("owner_id", ""),
                owner_username=owner.get("username"),
                owner_email=owner.get("email"),
                monthly_price_jpy=int(salon.get("monthly_price_jpy") or 0) if salon.get("monthly_price_jpy") is not None else None,
                allow_point_subscription=bool(salon.get("allow_point_subscription", True)),
                allow_jpy_subscription=bool(salon.get("allow_jpy_subscription", False)),
                active_members=active_members,
                pending_members=pending_members,
                canceled_members=canceled_members,
                total_members=total_members,
                risk_score=risk_result.score,
                risk_indicators=risk_result.indicators,
                created_at=salon.get("created_at", now_utc_iso()),
                updated_at=salon.get("updated_at", now_utc_iso()),
            ))

        return SalonModerationListResponse(
            data=items,
            total=len(items) if total is None else min(len(items), total),
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list salons for moderation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"サロンモデレーション一覧の取得に失敗しました: {exc}",
        )


@router.get("/salons/{salon_id}/moderation", response_model=SalonModerationDetailSchema)
async def get_salon_moderation_detail(
    salon_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        salon_response = (
            supabase
            .table("salons")
            .select("*")
            .eq("id", salon_id)
            .single()
            .execute()
        )
        salon = getattr(salon_response, "data", None)
        if not salon:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")

        owner_id = salon.get("owner_id")
        owner: Dict[str, Any] = {}
        if owner_id:
            owner_response = (
                supabase
                .table("users")
                .select("id,username,email,user_type")
                .eq("id", owner_id)
                .single()
                .execute()
            )
            owner = getattr(owner_response, "data", {}) or {}

        memberships_response = (
            supabase
            .table("salon_memberships")
            .select(
                "id,user_id,status,joined_at,last_charged_at,next_charge_at,canceled_at,metadata"
            )
            .eq("salon_id", salon_id)
            .order("joined_at", desc=True)
            .limit(200)
            .execute()
        )
        membership_rows, _ = handle_supabase_response(
            memberships_response,
            "admin salon membership detail",
            raise_on_error=False,
        )

        member_user_ids: Set[str] = {row.get("user_id") for row in membership_rows if row.get("user_id")}
        member_user_map: Dict[str, Dict[str, Any]] = {}
        if member_user_ids:
            member_users_response = (
                supabase
                .table("users")
                .select("id,username,email")
                .in_("id", list(member_user_ids))
                .execute()
            )
            member_user_rows, _ = handle_supabase_response(
                member_users_response,
                "admin salon member user lookup",
                raise_on_error=False,
            )
            for row in member_user_rows:
                if row.get("id"):
                    member_user_map[row["id"]] = row

        counts: Dict[str, int] = defaultdict(int)
        members: List[SalonMemberModerationSchema] = []
        for membership in membership_rows:
            status_value = (membership.get("status") or "").upper()
            counts[status_value] += 1
            user_info = member_user_map.get(membership.get("user_id"), {})
            members.append(SalonMemberModerationSchema(
                id=membership.get("id", ""),
                user_id=membership.get("user_id", ""),
                username=user_info.get("username"),
                email=user_info.get("email"),
                status=status_value,
                joined_at=membership.get("joined_at"),
                last_charged_at=membership.get("last_charged_at"),
                next_charge_at=membership.get("next_charge_at"),
                canceled_at=membership.get("canceled_at"),
            ))

        announcements_response = (
            supabase
            .table("salon_announcements")
            .select("id", count="exact")
            .eq("salon_id", salon_id)
            .execute()
        )
        _, announcements_count = handle_supabase_response(
            announcements_response,
            "admin salon announcements count",
            raise_on_error=False,
        )

        events_response = (
            supabase
            .table("salon_events")
            .select("id", count="exact")
            .eq("salon_id", salon_id)
            .execute()
        )
        _, events_count = handle_supabase_response(
            events_response,
            "admin salon events count",
            raise_on_error=False,
        )

        posts_response = (
            supabase
            .table("salon_posts")
            .select("id", count="exact")
            .eq("salon_id", salon_id)
            .execute()
        )
        _, posts_count = handle_supabase_response(
            posts_response,
            "admin salon posts count",
            raise_on_error=False,
        )

        active_members = counts.get("ACTIVE", 0)
        pending_members = counts.get("PENDING", 0) + counts.get("WAITING", 0)
        canceled_members = counts.get("CANCELED", 0) + counts.get("CANCELLED", 0)
        total_members = sum(counts.values()) if counts else active_members + pending_members + canceled_members

        risk_result = calculate_salon_risk(
            salon,
            active_members=active_members,
            pending_members=pending_members,
            canceled_members=canceled_members,
            monthly_price_jpy=salon.get("monthly_price_jpy"),
            refunds=0,
        )

        return SalonModerationDetailSchema(
            id=salon_id,
            title=salon.get("title", ""),
            status=salon.get("status", "approved"),
            is_active=bool(salon.get("is_active", True)),
            owner_id=owner_id or "",
            owner_username=owner.get("username"),
            owner_email=owner.get("email"),
            owner_user_type=owner.get("user_type"),
            monthly_price_jpy=int(salon.get("monthly_price_jpy") or 0) if salon.get("monthly_price_jpy") is not None else None,
            allow_point_subscription=bool(salon.get("allow_point_subscription", True)),
            allow_jpy_subscription=bool(salon.get("allow_jpy_subscription", False)),
            active_members=active_members,
            pending_members=pending_members,
            canceled_members=canceled_members,
            total_members=total_members,
            risk_score=risk_result.score,
            risk_indicators=risk_result.indicators,
            created_at=salon.get("created_at", now_utc_iso()),
            updated_at=salon.get("updated_at", now_utc_iso()),
            description=salon.get("description"),
            moderation_notes=salon.get("moderation_notes"),
            members=members,
            announcements_count=announcements_count or 0,
            events_count=events_count or 0,
            posts_count=posts_count or 0,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get salon moderation detail")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"サロンモデレーション詳細の取得に失敗しました: {exc}",
        )


@router.post("/salons/{salon_id}/status", response_model=UserActionResponse)
async def update_salon_status(
    salon_id: str,
    request: SalonStatusUpdateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        salon_response = (
            supabase
            .table("salons")
            .select("id,owner_id,status,is_active,moderation_notes")
            .eq("id", salon_id)
            .single()
            .execute()
        )
        salon = getattr(salon_response, "data", None)
        if not salon:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")

        update_data = {
            "status": request.status,
            "moderation_notes": request.moderation_notes,
            "updated_at": now_utc_iso(),
        }
        if request.status in {"approved"}:
            update_data["is_active"] = True
        elif request.status in {"suspended", "rejected"}:
            update_data["is_active"] = False

        supabase.table("salons").update(update_data).eq("id", salon_id).execute()

        create_moderation_event(
            supabase,
            action=f"salon_status_{request.status}",
            performed_by=admin.get("id"),
            target_user_id=salon.get("owner_id"),
            target_salon_id=salon_id,
            reason=request.reason,
            metadata={"moderation_notes": request.moderation_notes},
        )

        return UserActionResponse(
            salon_id=salon_id,
            user_id=salon.get("owner_id"),
            message="サロンステータスを更新しました",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update salon status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"サロンステータスの更新に失敗しました: {exc}",
        )


@router.post("/salons/{salon_id}/members/{membership_id}/action", response_model=UserActionResponse)
async def update_salon_member_status(
    salon_id: str,
    membership_id: str,
    request: SalonMemberActionRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        membership_response = (
            supabase
            .table("salon_memberships")
            .select("id,salon_id,user_id,status,metadata")
            .eq("id", membership_id)
            .single()
            .execute()
        )
        membership = getattr(membership_response, "data", None)
        if not membership or membership.get("salon_id") != salon_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会員情報が見つかりません")

        new_status = "ACTIVE" if request.action == "approve" else "CANCELED"
        update_data: Dict[str, Any] = {
            "status": new_status,
            "updated_at": now_utc_iso(),
        }
        if request.action == "cancel":
            update_data["canceled_at"] = now_utc_iso()

        metadata = membership.get("metadata") or {}
        metadata_key = "admin_notes"
        notes_list: List[str] = metadata.get(metadata_key, []) if isinstance(metadata.get(metadata_key), list) else []
        if request.reason:
            notes_list.append(f"{now_utc_iso()}: {request.reason}")
        metadata[metadata_key] = notes_list
        update_data["metadata"] = metadata

        supabase.table("salon_memberships").update(update_data).eq("id", membership_id).execute()

        create_moderation_event(
            supabase,
            action=f"salon_member_{request.action}",
            performed_by=admin.get("id"),
            target_user_id=membership.get("user_id"),
            target_salon_id=salon_id,
            reason=request.reason,
            metadata={"membership_id": membership_id, "new_status": new_status},
        )

        return UserActionResponse(
            salon_id=salon_id,
            user_id=membership.get("user_id"),
            message="サロン会員ステータスを更新しました",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update salon member status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"サロン会員ステータスの更新に失敗しました: {exc}",
        )


@router.get("/maintenance/modes", response_model=MaintenanceModeListResponse)
async def list_maintenance_modes(
    scope: Optional[str] = Query(None, description="対象スコープ"),
    status: Optional[str] = Query(None, description="ステータス"),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        query = supabase.table("maintenance_modes").select("*").order("created_at", desc=True)
        if scope:
            query = query.eq("scope", scope)
        if status:
            query = query.eq("status", status)
        response = query.execute()
        rows, _ = handle_supabase_response(response, "admin maintenance mode list")
        return MaintenanceModeListResponse(data=[build_maintenance_mode(row) for row in rows])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list maintenance modes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メンテナンスモード一覧の取得に失敗しました: {exc}",
        )


@router.post("/maintenance/modes", response_model=MaintenanceModeSchema, status_code=status.HTTP_201_CREATED)
async def create_maintenance_mode(
    request: MaintenanceModeCreateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        payload = {
            "scope": request.scope,
            "status": "scheduled",
            "title": request.title,
            "message": request.message,
            "planned_start": request.planned_start,
            "planned_end": request.planned_end,
            "created_by": admin.get("id"),
        }
        response = supabase.table("maintenance_modes").insert(payload).execute()
        mode_rows, _ = handle_supabase_response(response, "admin maintenance mode create")
        if not mode_rows:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="メンテナンスの登録に失敗しました")
        mode = mode_rows[0]

        create_moderation_event(
            supabase,
            action="maintenance_mode_create",
            performed_by=admin.get("id"),
            reason=request.message,
            metadata={"scope": request.scope, "title": request.title},
        )

        return build_maintenance_mode(mode)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create maintenance mode")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メンテナンスモードの作成に失敗しました: {exc}",
        )


@router.post("/maintenance/modes/{mode_id}/status", response_model=MaintenanceModeSchema)
async def update_maintenance_mode_status(
    mode_id: str,
    request: MaintenanceModeStatusUpdateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        mode_response = (
            supabase
            .table("maintenance_modes")
            .select("*")
            .eq("id", mode_id)
            .single()
            .execute()
        )
        mode = getattr(mode_response, "data", None)
        if not mode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メンテナンス設定が見つかりません")

        update_data: Dict[str, Any] = {
            "status": request.status,
            "message": request.message or mode.get("message"),
            "updated_at": now_utc_iso(),
        }
        now_value = now_utc_iso()
        if request.status == "active" and not mode.get("activated_at"):
            update_data["activated_at"] = now_value
        if request.status in {"completed", "cancelled"}:
            update_data["deactivated_at"] = now_value

        response = supabase.table("maintenance_modes").update(update_data).eq("id", mode_id).execute()
        updated_rows, _ = handle_supabase_response(response, "admin maintenance mode update")
        if not updated_rows:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="メンテナンス更新に失敗しました")
        updated = updated_rows[0]

        create_moderation_event(
            supabase,
            action=f"maintenance_mode_{request.status}",
            performed_by=admin.get("id"),
            reason=request.message,
            metadata={"mode_id": mode_id, "scope": updated.get("scope")},
        )

        return build_maintenance_mode(updated)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update maintenance mode status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メンテナンスステータスの更新に失敗しました: {exc}",
        )


@router.get("/maintenance/overview")
async def get_maintenance_overview(admin: dict = Depends(require_admin)):
    try:
        supabase = get_supabase()
        response = (
            supabase
            .table("maintenance_modes")
            .select("*")
            .order("planned_start", desc=True)
            .limit(200)
            .execute()
        )
        rows, _ = handle_supabase_response(response, "admin maintenance overview")
        active = [build_maintenance_mode(row) for row in rows if row.get("status") == "active"]
        scheduled = [build_maintenance_mode(row) for row in rows if row.get("status") == "scheduled"]
        completed = [build_maintenance_mode(row) for row in rows if row.get("status") in {"completed", "cancelled"}]
        return {
            "active": active,
            "scheduled": scheduled,
            "history": completed[:20],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get maintenance overview")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メンテナンス概要の取得に失敗しました: {exc}",
        )


@router.get("/maintenance/status-checks", response_model=SystemStatusCheckListResponse)
async def list_system_status_checks(
    component: Optional[str] = Query(None, description="対象コンポーネント"),
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        query = supabase.table("system_status_checks").select("*").order("checked_at", desc=True).limit(limit)
        if component:
            query = query.eq("component", component)
        response = query.execute()
        rows, _ = handle_supabase_response(response, "admin status check list")
        return SystemStatusCheckListResponse(data=[build_system_status_check(row) for row in rows])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list system status checks")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステータスチェック一覧の取得に失敗しました: {exc}",
        )


@router.post("/maintenance/status-checks", response_model=SystemStatusCheckSchema, status_code=status.HTTP_201_CREATED)
async def create_system_status_check(
    request: SystemStatusCheckCreateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        payload = {
            "component": request.component,
            "status": request.status,
            "response_time_ms": request.response_time_ms,
            "message": request.message,
            "created_by": admin.get("id"),
        }
        response = supabase.table("system_status_checks").insert(payload).execute()
        rows, _ = handle_supabase_response(response, "admin status check create")
        if not rows:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ステータスチェック登録に失敗しました")
        entry = rows[0]

        create_moderation_event(
            supabase,
            action="system_status_check",
            performed_by=admin.get("id"),
            metadata={
                "component": request.component,
                "status": request.status,
            },
        )

        return build_system_status_check(entry)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create system status check")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステータスチェックの登録に失敗しました: {exc}",
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
        lps = [lp for lp in lps if lp.get("seller_id")]
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
            if seller_map.get(lp.get("seller_id"), {}).get("email") not in EXCLUDED_EMAILS
        ]
        return AdminMarketplaceResponse(data=items, total=len(items))
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

        try:
            product_visibility = request.status == "published"
            supabase.table("products").update({
                "is_available": product_visibility,
                "updated_at": now_utc_iso(),
            }).eq("lp_id", lp_id).execute()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to sync product availability with LP status",
                extra={
                    "lp_id": lp_id,
                    "status": request.status,
                    "error": str(exc),
                },
            )

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


def _collect_user_map(supabase: Client, user_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = [uid for uid in set(user_ids) if uid]
    if not ids:
        return {}
    response = (
        supabase
        .table("users")
        .select("id, username")
        .in_("id", ids)
        .execute()
    )
    rows, _ = handle_supabase_response(response, "users lookup for featured panel", raise_on_error=False)
    return {row.get("id"): row for row in rows}


@router.get("/featured/products", response_model=FeaturedProductListResponse)
async def list_featured_products(
    search: Optional[str] = Query(None, description="商品タイトル検索"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    supabase = get_supabase()
    query = (
        supabase
        .table("products")
        .select("id,title,seller_id,lp_id,is_available,is_featured,created_at", count="exact")
    )
    if search:
        query = query.ilike("title", f"%{search}%")
    query = query.order("is_featured", desc=True).order("created_at", desc=True).range(offset, offset + limit - 1)
    response = query.execute()
    rows, total = handle_supabase_response(response, "featured products list")

    lp_ids = {row.get("lp_id") for row in rows if row.get("lp_id")}
    seller_ids = {row.get("seller_id") for row in rows if row.get("seller_id")}

    seller_map = _collect_user_map(supabase, seller_ids)

    lp_map: Dict[str, Dict[str, Any]] = {}
    if lp_ids:
        lp_response = (
            supabase
            .table("landing_pages")
            .select("id, slug")
            .in_("id", list(lp_ids))
            .execute()
        )
        lp_rows, _ = handle_supabase_response(lp_response, "landing pages lookup for featured", raise_on_error=False)
        for lp in lp_rows:
            lp_map[lp.get("id")] = lp

    items = [
        FeaturedProductSummary(
            id=row.get("id"),
            title=row.get("title", ""),
            lp_slug=(lp_map.get(row.get("lp_id"), {}) or {}).get("slug"),
            seller_username=(seller_map.get(row.get("seller_id"), {}) or {}).get("username"),
            is_available=bool(row.get("is_available", False)),
            is_featured=bool(row.get("is_featured", False)),
            created_at=row.get("created_at"),
        )
        for row in rows
    ]

    if total is None:
        total = len(items)

    return FeaturedProductListResponse(data=items, total=total)


@router.get("/featured/notes", response_model=FeaturedNoteListResponse)
async def list_featured_notes(
    search: Optional[str] = Query(None, description="NOTEタイトル検索"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    supabase = get_supabase()
    query = (
        supabase
        .table("notes")
        .select("id,title,slug,author_id,status,is_featured,published_at,created_at", count="exact")
        .eq("status", "published")
    )
    if search:
        query = query.ilike("title", f"%{search}%")
    query = query.order("is_featured", desc=True).order("published_at", desc=True).order("created_at", desc=True).range(offset, offset + limit - 1)
    response = query.execute()
    rows, total = handle_supabase_response(response, "featured notes list")

    author_ids = {row.get("author_id") for row in rows if row.get("author_id")}
    author_map = _collect_user_map(supabase, author_ids)

    items = [
        FeaturedNoteSummary(
            id=row.get("id"),
            title=row.get("title", ""),
            slug=row.get("slug"),
            author_username=(author_map.get(row.get("author_id"), {}) or {}).get("username"),
            status=row.get("status"),
            is_featured=bool(row.get("is_featured", False)),
            published_at=row.get("published_at") or row.get("created_at"),
        )
        for row in rows
    ]

    if total is None:
        total = len(items)

    return FeaturedNoteListResponse(data=items, total=total)


@router.get("/featured/salons", response_model=FeaturedSalonListResponse)
async def list_featured_salons(
    search: Optional[str] = Query(None, description="サロンタイトル検索"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    supabase = get_supabase()
    query = (
        supabase
        .table("salons")
        .select("id,title,owner_id,is_active,is_featured,created_at", count="exact")
        .eq("is_active", True)
    )
    if search:
        query = query.ilike("title", f"%{search}%")
    query = query.order("is_featured", desc=True).order("created_at", desc=True).range(offset, offset + limit - 1)
    response = query.execute()
    rows, total = handle_supabase_response(response, "featured salons list")

    owner_ids = {row.get("owner_id") for row in rows if row.get("owner_id")}
    owner_map = _collect_user_map(supabase, owner_ids)

    items = [
        FeaturedSalonSummary(
            id=row.get("id"),
            title=row.get("title", ""),
            owner_username=(owner_map.get(row.get("owner_id"), {}) or {}).get("username"),
            is_active=bool(row.get("is_active", False)),
            is_featured=bool(row.get("is_featured", False)),
            created_at=row.get("created_at"),
        )
        for row in rows
    ]

    if total is None:
        total = len(items)

    return FeaturedSalonListResponse(data=items, total=total)


@router.post("/featured/toggle", response_model=FeaturedToggleResponse)
async def toggle_featured_flag(
    request: FeaturedItemToggleRequest,
    admin: dict = Depends(require_admin),
):
    supabase = get_supabase()

    table_map = {
        "product": {
            "table": "products",
            "id_field": "id",
            "title_field": "title",
            "owner_field": "seller_id",
            "extra_fields": ["lp_id"],
        },
        "note": {
            "table": "notes",
            "id_field": "id",
            "title_field": "title",
            "owner_field": "author_id",
            "extra_fields": [],
        },
        "salon": {
            "table": "salons",
            "id_field": "id",
            "title_field": "title",
            "owner_field": "owner_id",
            "extra_fields": [],
        },
    }

    meta = table_map.get(request.entity_type)
    if not meta:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不正なエンティティ種別です")

    select_fields = [meta["id_field"], meta["title_field"], meta["owner_field"], "is_featured"]
    for extra in meta.get("extra_fields", []):
        if extra not in select_fields:
            select_fields.append(extra)
    record_response = (
        supabase
        .table(meta["table"])
        .select(",".join(select_fields))
        .eq(meta["id_field"], request.entity_id)
        .single()
        .execute()
    )

    record = record_response.data
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="対象が見つかりません")

    update_payload = {
        "is_featured": request.is_featured,
        "updated_at": now_utc_iso(),
    }
    supabase.table(meta["table"]).update(update_payload).eq(meta["id_field"], request.entity_id).execute()

    action = f"{request.entity_type}_featured_{'on' if request.is_featured else 'off'}"
    owner_id = record.get(meta["owner_field"])
    target_kwargs = {
        "target_user_id": owner_id,
    }
    if request.entity_type == "note":
        target_kwargs["target_note_id"] = request.entity_id
    elif request.entity_type == "salon":
        target_kwargs["target_salon_id"] = request.entity_id
    else:
        target_kwargs["target_lp_id"] = record.get("lp_id")

    create_moderation_event(
        supabase,
        action=action,
        performed_by=admin.get("id"),
        metadata={
            "entity_type": request.entity_type,
            "entity_id": request.entity_id,
        },
        **target_kwargs,
    )

    return FeaturedToggleResponse(
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        title=record.get(meta["title_field"], ""),
        is_featured=request.is_featured,
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
            .select("user_id, transaction_type, amount, created_at")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        transactions, _ = handle_supabase_response(transactions_response, "point transactions for analytics")
        user_ids = {tx.get("user_id") for tx in transactions if tx.get("user_id")}
        user_email_map: Dict[str, str] = {}
        if user_ids:
            users_response = (
                supabase
                .table("users")
                .select("id, email")
                .in_("id", list(user_ids))
                .execute()
            )
            user_rows, _ = handle_supabase_response(users_response, "user email lookup for analytics")
            for row in user_rows:
                if row.get("id") and row.get("email"):
                    user_email_map[row["id"]] = row["email"]
        cutoff = datetime.now(timezone.utc) - timedelta(days=limit_days)
        totals = {"purchased": 0, "spent": 0, "granted": 0, "other": 0, "net": 0}
        daily: Dict[str, Dict[str, int]] = defaultdict(lambda: {"purchased": 0, "spent": 0, "granted": 0, "other": 0, "net": 0})
        monthly: Dict[str, Dict[str, int]] = defaultdict(lambda: {"purchased": 0, "spent": 0, "granted": 0, "other": 0, "net": 0})
        for tx in transactions:
            dt = parse_iso_datetime(tx.get("created_at"))
            if not dt:
                continue
            user_email = user_email_map.get(tx.get("user_id"))
            if user_email and user_email in EXCLUDED_EMAILS:
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


@router.get("/announcements", response_model=AdminAnnouncementListResponse)
async def list_admin_announcements(
    include_unpublished: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        query = (
            supabase
            .table("announcements")
            .select("*", count="exact")
            .order("published_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if not include_unpublished:
            query = query.eq("is_published", True)
        response = query.execute()
        rows, total = handle_supabase_response(response, "admin announcements list")
        announcements = [build_admin_announcement(row) for row in rows]
        return AdminAnnouncementListResponse(
            data=announcements,
            total=total if total is not None else len(announcements),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list announcements")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"お知らせ一覧の取得に失敗しました: {exc}",
        )


@router.post("/announcements", response_model=AdminAnnouncementSchema, status_code=status.HTTP_201_CREATED)
async def create_admin_announcement(
    request: AnnouncementCreateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        published_at = normalize_published_at(request.published_at)
        insert_data = {
            "title": request.title.strip(),
            "summary": request.summary.strip(),
            "body": request.body,
            "is_published": request.is_published,
            "highlight": request.highlight,
            "published_at": published_at,
            "created_by": admin.get("id"),
            "created_by_email": admin.get("email"),
            "created_by_username": admin.get("username"),
        }
        response = (
            supabase
            .table("announcements")
            .insert(insert_data)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="お知らせの作成に失敗しました",
            )
        announcement = build_admin_announcement(rows[0])
        create_moderation_event(
            supabase,
            action="announcement_create",
            performed_by=admin.get("id"),
            reason=f"{announcement.title} を公開",
        )
        return announcement
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create announcement")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"お知らせの作成に失敗しました: {exc}",
        )


@router.put("/announcements/{announcement_id}", response_model=AdminAnnouncementSchema)
async def update_admin_announcement(
    announcement_id: str,
    request: AnnouncementUpdateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        update_data: Dict[str, Any] = {}
        if request.title is not None:
            update_data["title"] = request.title.strip()
        if request.summary is not None:
            update_data["summary"] = request.summary.strip()
        if request.body is not None:
            update_data["body"] = request.body
        if request.is_published is not None:
            update_data["is_published"] = request.is_published
        if request.highlight is not None:
            update_data["highlight"] = request.highlight
        if request.published_at is not None:
            update_data["published_at"] = normalize_published_at(request.published_at)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="更新内容がありません",
            )
        update_data["updated_at"] = now_utc_iso()
        response = (
            supabase
            .table("announcements")
            .update(update_data)
            .eq("id", announcement_id)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたお知らせが見つかりません",
            )
        announcement = build_admin_announcement(rows[0])
        create_moderation_event(
            supabase,
            action="announcement_update",
            performed_by=admin.get("id"),
            reason=f"{announcement.title} を更新",
        )
        return announcement
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update announcement")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"お知らせの更新に失敗しました: {exc}",
        )


@router.delete("/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_announcement(
    announcement_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        supabase = get_supabase()
        existing = (
            supabase
            .table("announcements")
            .select("id, title")
            .eq("id", announcement_id)
            .single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたお知らせが見つかりません",
            )
        supabase.table("announcements").delete().eq("id", announcement_id).execute()
        create_moderation_event(
            supabase,
            action="announcement_delete",
            performed_by=admin.get("id"),
            reason=f"{existing.data.get('title', '')} を削除",
        )
        return None
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete announcement")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"お知らせの削除に失敗しました: {exc}",
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


# ========================================
# NOTE Share Management (シェア管理)
# ========================================

class ShareOverviewStats(BaseModel):
    total_shares: int
    total_reward_points: int
    today_shares: int
    this_week_shares: int
    this_month_shares: int


class TopCreator(BaseModel):
    user_id: str
    username: str
    email: str
    total_shares: int
    total_reward_points: int


class TopNote(BaseModel):
    note_id: str
    title: str
    author_username: str
    share_count: int
    total_reward_points: int


class UserShareStats(BaseModel):
    user_id: str
    username: str
    email: str
    total_shares: int
    total_reward_points: int
    last_share_at: Optional[str]


class NoteShareStats(BaseModel):
    note_id: str
    title: str
    author_username: str
    share_count: int
    total_reward_points: int


class ShareLogItem(BaseModel):
    id: str
    note_id: str
    note_title: str
    author_username: str
    shared_by_user_id: str
    shared_by_username: str
    tweet_id: str
    tweet_url: str
    shared_at: str
    verified: bool
    points_amount: int
    is_suspicious: bool
    ip_address: Optional[str]
    admin_notes: Optional[str]


class FraudAlert(BaseModel):
    id: str
    alert_type: str
    severity: str
    description: Optional[str]
    note_id: Optional[str]
    note_title: Optional[str]
    user_id: Optional[str]
    username: Optional[str]
    resolved: bool
    resolved_by: Optional[str]
    resolved_at: Optional[str]
    created_at: str


class RewardSettings(BaseModel):
    id: str
    points_per_share: int
    updated_by: Optional[str]
    updated_at: str


@router.get("/share-stats/overview", response_model=ShareOverviewStats)
async def get_share_overview_stats(admin: dict = Depends(require_admin)):
    """
    全体シェア統計サマリー
    """
    try:
        supabase = get_supabase()
        
        # 全シェア取得
        all_shares = supabase.table("note_shares").select("shared_at, points_amount").execute()
        shares = all_shares.data if all_shares.data else []
        
        total_shares = len(shares)
        total_reward_points = sum(s.get("points_amount", 0) for s in shares)
        
        # 今日・今週・今月のシェア数
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)
        
        today_shares = sum(
            1 for s in shares
            if parse_iso_datetime(s.get("shared_at", "")) and parse_iso_datetime(s.get("shared_at", "")) >= today_start
        )
        
        this_week_shares = sum(
            1 for s in shares
            if parse_iso_datetime(s.get("shared_at", "")) and parse_iso_datetime(s.get("shared_at", "")) >= week_start
        )
        
        this_month_shares = sum(
            1 for s in shares
            if parse_iso_datetime(s.get("shared_at", "")) and parse_iso_datetime(s.get("shared_at", "")) >= month_start
        )
        
        return ShareOverviewStats(
            total_shares=total_shares,
            total_reward_points=total_reward_points,
            today_shares=today_shares,
            this_week_shares=this_week_shares,
            this_month_shares=this_month_shares
        )
    
    except Exception as e:
        logger.exception("Failed to get share overview stats")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"統計取得に失敗しました: {str(e)}"
        )


@router.get("/share-stats/top-creators")
async def get_top_creators(
    limit: int = Query(10, ge=1, le=100),
    admin: dict = Depends(require_admin)
):
    """
    トップインフォプレナー（シェア数順）
    """
    try:
        supabase = get_supabase()
        
        # 全シェアとNOTE情報を結合
        shares_response = supabase.table("note_shares").select(
            "note_id, points_amount"
        ).execute()
        
        shares = shares_response.data if shares_response.data else []
        
        # note_id -> author_id のマッピング
        note_ids = list(set(s["note_id"] for s in shares))
        
        if not note_ids:
            return []
        
        notes_response = supabase.table("notes").select("id, author_id").in_("id", note_ids).execute()
        notes = notes_response.data if notes_response.data else []
        
        note_to_author = {n["id"]: n["author_id"] for n in notes}
        
        # author_id ごとに集計
        author_stats = defaultdict(lambda: {"share_count": 0, "reward_points": 0})
        
        for share in shares:
            author_id = note_to_author.get(share["note_id"])
            if author_id:
                author_stats[author_id]["share_count"] += 1
                author_stats[author_id]["reward_points"] += share.get("points_amount", 0)
        
        # ユーザー情報取得
        author_ids = list(author_stats.keys())
        users_response = supabase.table("users").select("id, username, email").in_("id", author_ids).execute()
        users = users_response.data if users_response.data else []
        
        user_map = {u["id"]: u for u in users}
        
        # トップクリエイター作成
        top_creators = []
        for author_id, stats in author_stats.items():
            user = user_map.get(author_id)
            if user:
                top_creators.append(TopCreator(
                    user_id=author_id,
                    username=user.get("username", "Unknown"),
                    email=user.get("email", ""),
                    total_shares=stats["share_count"],
                    total_reward_points=stats["reward_points"]
                ))
        
        # ソート
        top_creators.sort(key=lambda x: x.total_shares, reverse=True)
        
        return top_creators[:limit]
    
    except Exception as e:
        logger.exception("Failed to get top creators")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"トップクリエイター取得に失敗しました: {str(e)}"
        )


@router.get("/share-stats/top-notes")
async def get_top_notes(
    limit: int = Query(10, ge=1, le=100),
    admin: dict = Depends(require_admin)
):
    """
    トップNOTE（シェア数順）
    """
    try:
        supabase = get_supabase()
        
        # シェア集計
        shares_response = supabase.table("note_shares").select("note_id, points_amount").execute()
        shares = shares_response.data if shares_response.data else []
        
        note_stats = defaultdict(lambda: {"count": 0, "points": 0})
        for share in shares:
            note_id = share["note_id"]
            note_stats[note_id]["count"] += 1
            note_stats[note_id]["points"] += share.get("points_amount", 0)
        
        # NOTE情報取得
        note_ids = list(note_stats.keys())
        if not note_ids:
            return []
        
        notes_response = supabase.table("notes").select("id, title, author_id").in_("id", note_ids).execute()
        notes = notes_response.data if notes_response.data else []
        
        # 著者情報取得
        author_ids = [n["author_id"] for n in notes]
        users_response = supabase.table("users").select("id, username").in_("id", author_ids).execute()
        users = users_response.data if users_response.data else []
        
        user_map = {u["id"]: u["username"] for u in users}
        
        # トップNOTE作成
        top_notes = []
        for note in notes:
            note_id = note["id"]
            stats = note_stats.get(note_id, {"count": 0, "points": 0})
            top_notes.append(TopNote(
                note_id=note_id,
                title=note.get("title", "Untitled"),
                author_username=user_map.get(note["author_id"], "Unknown"),
                share_count=stats["count"],
                total_reward_points=stats["points"]
            ))
        
        # ソート
        top_notes.sort(key=lambda x: x.share_count, reverse=True)
        
        return top_notes[:limit]
    
    except Exception as e:
        logger.exception("Failed to get top notes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"トップNOTE取得に失敗しました: {str(e)}"
        )


@router.get("/shares")
async def get_all_shares(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    suspicious_only: bool = Query(False),
    admin: dict = Depends(require_admin)
):
    """
    全シェアログ（詳細）
    """
    try:
        supabase = get_supabase()
        
        # クエリ構築
        query = supabase.table("note_shares").select(
            "id, note_id, user_id, tweet_id, tweet_url, shared_at, verified, points_amount, is_suspicious, ip_address, admin_notes"
        )
        
        if suspicious_only:
            query = query.eq("is_suspicious", True)
        
        query = query.order("shared_at", desc=True).range(offset, offset + limit - 1)
        
        shares_response = query.execute()
        shares = shares_response.data if shares_response.data else []
        
        # NOTE情報取得
        note_ids = list(set(s["note_id"] for s in shares))
        notes_map = {}
        if note_ids:
            notes_response = supabase.table("notes").select("id, title, author_id").in_("id", note_ids).execute()
            notes = notes_response.data if notes_response.data else []
            notes_map = {n["id"]: n for n in notes}
        
        # ユーザー情報取得
        user_ids = list(set(s["user_id"] for s in shares))
        author_ids = [notes_map[s["note_id"]]["author_id"] for s in shares if s["note_id"] in notes_map]
        all_user_ids = list(set(user_ids + author_ids))
        
        users_map = {}
        if all_user_ids:
            users_response = supabase.table("users").select("id, username").in_("id", all_user_ids).execute()
            users = users_response.data if users_response.data else []
            users_map = {u["id"]: u["username"] for u in users}
        
        # シェアログ構築
        share_logs = []
        for share in shares:
            note = notes_map.get(share["note_id"], {})
            share_logs.append(ShareLogItem(
                id=share["id"],
                note_id=share["note_id"],
                note_title=note.get("title", "Unknown"),
                author_username=users_map.get(note.get("author_id"), "Unknown"),
                shared_by_user_id=share["user_id"],
                shared_by_username=users_map.get(share["user_id"], "Unknown"),
                tweet_id=share["tweet_id"],
                tweet_url=share["tweet_url"],
                shared_at=share["shared_at"],
                verified=share["verified"],
                points_amount=share.get("points_amount", 0),
                is_suspicious=share["is_suspicious"],
                ip_address=share.get("ip_address"),
                admin_notes=share.get("admin_notes")
            ))
        
        return share_logs
    
    except Exception as e:
        logger.exception("Failed to get share logs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"シェアログ取得に失敗しました: {str(e)}"
        )


@router.get("/fraud-alerts")
async def get_fraud_alerts(
    resolved: bool = Query(False),
    admin: dict = Depends(require_admin)
):
    """
    不正検知アラート一覧
    """
    try:
        supabase = get_supabase()
        
        query = supabase.table("share_fraud_alerts").select(
            "id, alert_type, severity, description, note_id, user_id, resolved, resolved_by, resolved_at, created_at"
        ).eq("resolved", resolved).order("created_at", desc=True)
        
        alerts_response = query.execute()
        alerts = alerts_response.data if alerts_response.data else []
        
        # NOTE・ユーザー情報取得
        note_ids = [a["note_id"] for a in alerts if a.get("note_id")]
        user_ids = [a["user_id"] for a in alerts if a.get("user_id")]
        resolved_by_ids = [a["resolved_by"] for a in alerts if a.get("resolved_by")]
        
        all_user_ids = list(set(user_ids + resolved_by_ids))
        
        notes_map = {}
        if note_ids:
            notes_response = supabase.table("notes").select("id, title").in_("id", note_ids).execute()
            notes = notes_response.data if notes_response.data else []
            notes_map = {n["id"]: n["title"] for n in notes}
        
        users_map = {}
        if all_user_ids:
            users_response = supabase.table("users").select("id, username").in_("id", all_user_ids).execute()
            users = users_response.data if users_response.data else []
            users_map = {u["id"]: u["username"] for u in users}
        
        # アラート構築
        fraud_alerts = []
        for alert in alerts:
            fraud_alerts.append(FraudAlert(
                id=alert["id"],
                alert_type=alert["alert_type"],
                severity=alert["severity"],
                description=alert.get("description"),
                note_id=alert.get("note_id"),
                note_title=notes_map.get(alert.get("note_id")) if alert.get("note_id") else None,
                user_id=alert.get("user_id"),
                username=users_map.get(alert.get("user_id")) if alert.get("user_id") else None,
                resolved=alert["resolved"],
                resolved_by=users_map.get(alert.get("resolved_by")) if alert.get("resolved_by") else None,
                resolved_at=alert.get("resolved_at"),
                created_at=alert["created_at"]
            ))
        
        return fraud_alerts
    
    except Exception as e:
        logger.exception("Failed to get fraud alerts")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"不正アラート取得に失敗しました: {str(e)}"
        )


@router.patch("/fraud-alerts/{alert_id}/resolve")
async def resolve_fraud_alert(
    alert_id: str,
    admin: dict = Depends(require_admin)
):
    """
    不正アラートを解決済みにする
    """
    try:
        supabase = get_supabase()
        
        supabase.table("share_fraud_alerts").update({
            "resolved": True,
            "resolved_by": admin["id"],
            "resolved_at": now_utc_iso()
        }).eq("id", alert_id).execute()
        
        return {"message": "アラートを解決済みにしました"}
    
    except Exception as e:
        logger.exception("Failed to resolve fraud alert")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"アラート解決に失敗しました: {str(e)}"
        )


@router.get("/share-reward-settings", response_model=RewardSettings)
async def get_reward_settings(admin: dict = Depends(require_admin)):
    """
    現在の報酬レート取得
    """
    try:
        supabase = get_supabase()
        
        response = supabase.table("share_reward_settings").select(
            "id, points_per_share, updated_by, updated_at"
        ).order("updated_at", desc=True).limit(1).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="報酬設定が見つかりません"
            )
        
        settings_data = response.data[0]
        
        return RewardSettings(
            id=settings_data["id"],
            points_per_share=settings_data["points_per_share"],
            updated_by=settings_data.get("updated_by"),
            updated_at=settings_data["updated_at"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get reward settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"報酬設定取得に失敗しました: {str(e)}"
        )


class UpdateRewardRateRequest(BaseModel):
    points_per_share: int = Field(..., ge=0, le=1000)


@router.put("/share-reward-settings")
async def update_reward_settings(
    request: UpdateRewardRateRequest,
    admin: dict = Depends(require_admin)
):
    """
    報酬レート更新
    """
    try:
        supabase = get_supabase()
        
        new_setting = {
            "points_per_share": request.points_per_share,
            "updated_by": admin["id"]
        }
        
        supabase.table("share_reward_settings").insert(new_setting).execute()
        
        create_moderation_event(
            supabase,
            action="share_reward_rate_update",
            performed_by=admin["id"],
            reason=f"報酬レートを {request.points_per_share}P/シェア に変更"
        )
        
        return {"message": f"報酬レートを{request.points_per_share}ポイント/シェアに更新しました"}
    
    except Exception as e:
        logger.exception("Failed to update reward settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"報酬設定更新に失敗しました: {str(e)}"
        )
