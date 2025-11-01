from __future__ import annotations

import logging
import re
import secrets
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Literal

from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from postgrest.exceptions import APIError

from app.config import settings
from app.models.note import (
    NoteCreateRequest,
    NoteUpdateRequest,
    NoteDetailResponse,
    NoteListResponse,
    NoteSummaryResponse,
    PublicNoteListResponse,
    PublicNoteSummary,
    PublicNoteDetailResponse,
    NotePurchaseResponse,
    NoteMetricsResponse,
    NoteMetricsTopNote,
    OfficialShareSetupRequest,
    OfficialShareConfigResponse,
)
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/notes", tags=["notes"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

JPY_TO_USD_RATE = 145.0


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def get_current_user_id(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証情報が提供されていません",
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なトークンです",
        )
    return user_id


def get_optional_user_id(credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        return payload.get("sub")
    except Exception:
        return None


def normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = secrets.token_hex(3)
    return slug[:120]


def _coerce_float(value: Optional[Any]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive conversion
        return None


TWEET_ID_REGEX = re.compile(r"(?:status|statuses)/(?P<tweet_id>\d+)")


def extract_tweet_id(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    candidate = raw.strip()
    if candidate.isdigit():
        return candidate

    match = TWEET_ID_REGEX.search(candidate)
    if match:
        return match.group("tweet_id")

    # fallback for direct ID query parameter (?tweet_id=123)
    query_match = re.search(r"tweet_id=(\d+)", candidate)
    if query_match:
        return query_match.group(1)

    return None


def generate_unique_slug(supabase: Client, base_slug: str, exclude_note_id: Optional[str] = None) -> str:
    slug = base_slug
    suffix = 1
    while True:
        query = supabase.table("notes").select("id").eq("slug", slug)
        if exclude_note_id:
            query = query.neq("id", exclude_note_id)
        result = query.limit(1).execute()
        if not result.data:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


def map_note_summary(record: Dict[str, Any]) -> NoteSummaryResponse:
    return NoteSummaryResponse(
        id=record["id"],
        author_id=record["author_id"],
        title=record.get("title", ""),
        slug=record.get("slug", ""),
        cover_image_url=record.get("cover_image_url"),
        excerpt=record.get("excerpt"),
        is_paid=bool(record.get("is_paid")),
        price_points=int(record.get("price_points") or 0),
        price_jpy=int(record.get("price_jpy")) if record.get("price_jpy") is not None else None,
        allow_point_purchase=bool(record.get("allow_point_purchase", True)),
        allow_jpy_purchase=bool(record.get("allow_jpy_purchase", False)),
        tax_rate=_coerce_float(record.get("tax_rate")),
        tax_inclusive=bool(record.get("tax_inclusive", True)),
        status=record.get("status", "draft"),
        published_at=record.get("published_at"),
        updated_at=record.get("updated_at"),
        categories=list(record.get("categories") or []),
        allow_share_unlock=bool(record.get("allow_share_unlock", False)),
        official_share_tweet_id=record.get("official_share_tweet_id"),
        official_share_tweet_url=record.get("official_share_tweet_url"),
        official_share_x_user_id=record.get("official_share_x_user_id"),
        official_share_x_username=record.get("official_share_x_username"),
        official_share_set_at=record.get("official_share_set_at"),
    )


def map_note_detail(record: Dict[str, Any], salon_ids: Optional[List[str]] = None) -> NoteDetailResponse:
    summary = map_note_summary(record)
    content_blocks = record.get("content_blocks") or []
    return NoteDetailResponse(
        **summary.dict(),
        content_blocks=content_blocks,
        salon_access_ids=salon_ids or [],
    )


def ensure_note_access(note: Dict[str, Any], user_id: str) -> None:
    if note.get("author_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このノートにアクセスする権限がありません",
        )


def _fetch_note_salon_ids(supabase: Client, note_id: str) -> List[str]:
    response = (
        supabase
        .table("note_salon_access")
        .select("salon_id")
        .eq("note_id", note_id)
        .eq("allow_free_access", True)
        .execute()
    )
    return [row.get("salon_id") for row in response.data or [] if row.get("salon_id")]


def _sanitize_owned_salons(supabase: Client, owner_id: str, salon_ids: List[str]) -> List[str]:
    if not salon_ids:
        return []
    response = (
        supabase
        .table("salons")
        .select("id")
        .eq("owner_id", owner_id)
        .in_("id", salon_ids)
        .execute()
    )
    owned = {row.get("id") for row in response.data or []}
    return [sid for sid in salon_ids if sid in owned]


def _sync_note_salon_access(supabase: Client, note_id: str, owner_id: str, salon_ids: List[str]) -> List[str]:
    allowed_ids = _sanitize_owned_salons(supabase, owner_id, salon_ids)
    supabase.table("note_salon_access").delete().eq("note_id", note_id).execute()
    if allowed_ids:
        records = [
            {
                "note_id": note_id,
                "salon_id": sid,
                "allow_free_access": True,
            }
            for sid in allowed_ids
        ]
        supabase.table("note_salon_access").insert(records).execute()
    return allowed_ids


def _user_has_active_salon_access(supabase: Client, user_id: str, salon_ids: List[str]) -> bool:
    if not salon_ids:
        return False
    response = (
        supabase
        .table("salon_memberships")
        .select("status")
        .eq("user_id", user_id)
        .in_("salon_id", salon_ids)
        .execute()
    )
    for row in response.data or []:
        status_value = str(row.get("status", "")).upper()
        if status_value == "ACTIVE":
            return True
    return False


def _purchase_note_via_rpc(supabase: Client, note_id: str, user_id: str) -> NotePurchaseResponse:
    try:
        rpc_response = supabase.rpc(
            "purchase_note_with_points",
            {
                "p_note_id": note_id,
                "p_buyer_id": user_id,
            },
        ).execute()
    except APIError as exc:
        code_map = {
            "P0002": status.HTTP_404_NOT_FOUND,
            "P0001": status.HTTP_400_BAD_REQUEST,
            "23505": status.HTTP_409_CONFLICT,
        }
        error_message = exc.message or "購入処理に失敗しました"
        raise HTTPException(status_code=code_map.get(exc.code, status.HTTP_500_INTERNAL_SERVER_ERROR), detail=error_message)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc) or "購入処理に失敗しました")

    rpc_error = getattr(rpc_response, "error", None)
    if rpc_error:
        error_message = getattr(rpc_error, "message", None) or "購入処理に失敗しました"
        error_code = getattr(rpc_error, "code", None)
        code_map = {
            "P0002": status.HTTP_404_NOT_FOUND,
            "P0001": status.HTTP_400_BAD_REQUEST,
            "23505": status.HTTP_409_CONFLICT,
        }
        raise HTTPException(status_code=code_map.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR), detail=error_message)

    payload = rpc_response.data if rpc_response else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="購入処理で不明なエラーが発生しました")

    result = payload[0] if isinstance(payload, list) else payload
    points_spent = int(result.get("points_spent") or 0)
    remaining_points = int(result.get("remaining_points") or 0)

    return NotePurchaseResponse(
        note_id=note_id,
        points_spent=points_spent,
        remaining_points=remaining_points,
        purchased_at=result.get("purchased_at"),
        payment_method="points",
    )


@router.post("", response_model=NoteDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    data: NoteCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    base_slug = normalize_slug(data.title)
    slug = generate_unique_slug(supabase, base_slug)

    allow_point_purchase = data.allow_point_purchase if data.is_paid else False
    allow_jpy_purchase = data.allow_jpy_purchase if data.is_paid else False

    if data.is_paid and not (allow_point_purchase or allow_jpy_purchase):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="有料NOTEには決済手段を1つ以上有効にしてください"
        )

    if allow_point_purchase and (data.price_points is None or data.price_points <= 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ポイント決済を有効にする場合は price_points を設定してください"
        )

    if allow_jpy_purchase and (data.price_jpy is None or data.price_jpy <= 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="日本円決済を有効にする場合は price_jpy を設定してください"
        )

    price_points = data.price_points if allow_point_purchase else 0
    price_jpy = data.price_jpy if allow_jpy_purchase else None
    is_paid_flag = bool(data.is_paid and (allow_point_purchase or allow_jpy_purchase))

    note_data = {
        "author_id": user_id,
        "title": data.title,
        "slug": slug,
        "cover_image_url": data.cover_image_url,
        "excerpt": data.excerpt,
        "content_blocks": [block.model_dump() for block in data.content_blocks],
        "is_paid": is_paid_flag,
        "price_points": price_points,
        "price_jpy": price_jpy,
        "allow_point_purchase": allow_point_purchase,
        "allow_jpy_purchase": allow_jpy_purchase,
        "tax_rate": data.tax_rate if data.tax_rate is not None else 10.0,
        "tax_inclusive": data.tax_inclusive,
        "status": "draft",
        "categories": data.categories,
    }

    response = supabase.table("notes").insert(note_data).execute()
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ノートの作成に失敗しました",
        )
    note_record = response.data[0]

    salon_ids = _sync_note_salon_access(supabase, note_record["id"], user_id, data.salon_ids)

    return map_note_detail(note_record, salon_ids=salon_ids)


@router.get("", response_model=NoteListResponse)
async def list_notes(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    status_filter: Optional[str] = Query(None, pattern="^(draft|published)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    query = (
        supabase
        .table("notes")
        .select("*", count="exact")
        .eq("author_id", user_id)
        .order("updated_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status_filter:
        query = query.eq("status", status_filter)

    response = query.execute()
    notes = [map_note_summary(record) for record in response.data or []]
    total = getattr(response, "count", None) or len(notes)

    return NoteListResponse(
        data=notes,
        total=total,
        limit=limit,
        offset=offset,
    )


def _parse_datetime(value: Optional[Any]) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


@router.get("/metrics", response_model=NoteMetricsResponse)
async def get_note_metrics(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    try:
        notes_response = (
            supabase
            .table("notes")
            .select("id,title,slug,status,is_paid,price_points,published_at,created_at,categories")
            .eq("author_id", user_id)
            .execute()
        )

        notes = notes_response.data or []
        total_notes = len(notes)
        published_notes = sum(1 for note in notes if note.get("status") == "published")
        draft_notes = sum(1 for note in notes if note.get("status") == "draft")
        paid_notes = sum(1 for note in notes if note.get("is_paid"))
        free_notes = total_notes - paid_notes

        note_ids = [note.get("id") for note in notes if note.get("id")]
        purchases: List[Dict[str, Any]] = []
        if note_ids:
            purchases_response = (
                supabase
                .table("note_purchases")
                .select("note_id, points_spent, purchased_at")
                .in_("note_id", note_ids)
                .execute()
            )
            purchases = purchases_response.data or []

        total_sales_points = 0
        total_sales_count = 0
        monthly_sales_points = 0
        monthly_sales_count = 0
        purchase_count_by_note = defaultdict(int)
        purchase_points_by_note = defaultdict(int)

        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)

        for purchase in purchases:
            note_id = purchase.get("note_id")
            if not note_id:
                continue
            points = int(purchase.get("points_spent") or 0)
            total_sales_points += points
            total_sales_count += 1
            purchase_count_by_note[note_id] += 1
            purchase_points_by_note[note_id] += points

            purchased_at = _parse_datetime(purchase.get("purchased_at"))
            if purchased_at and purchased_at >= thirty_days_ago:
                monthly_sales_points += points
                monthly_sales_count += 1

        published_dates = [
            _parse_datetime(note.get("published_at"))
            for note in notes
            if note.get("published_at")
        ]
        latest_published_at = max([dt for dt in published_dates if dt], default=None)
        recent_published_count = sum(1 for dt in published_dates if dt and dt >= thirty_days_ago)

        paid_prices = [int(note.get("price_points") or 0) for note in notes if note.get("is_paid")]
        average_paid_price = int(round(sum(paid_prices) / len(paid_prices))) if paid_prices else 0

        categories_counter: Counter[str] = Counter()
        for note in notes:
            for category in note.get("categories") or []:
                if isinstance(category, str) and category.strip():
                    categories_counter[category.strip()] += 1
        top_categories = [category for category, _ in categories_counter.most_common(5)]

        note_lookup = {note.get("id"): note for note in notes if note.get("id")}
        top_note_id = None
        best_count = 0
        best_points = 0
        for note_id, count in purchase_count_by_note.items():
            points = purchase_points_by_note.get(note_id, 0)
            if count > best_count or (count == best_count and points > best_points):
                top_note_id = note_id
                best_count = count
                best_points = points

        top_note: Optional[NoteMetricsTopNote] = None
        if top_note_id and top_note_id in note_lookup:
            note = note_lookup[top_note_id]
            top_note = NoteMetricsTopNote(
                note_id=top_note_id,
                title=note.get("title", ""),
                slug=note.get("slug"),
                purchase_count=best_count,
                points_earned=best_points,
            )

        return NoteMetricsResponse(
            total_notes=total_notes,
            published_notes=published_notes,
            draft_notes=draft_notes,
            paid_notes=paid_notes,
            free_notes=free_notes,
            total_sales_count=total_sales_count,
            total_sales_points=total_sales_points,
            monthly_sales_count=monthly_sales_count,
            monthly_sales_points=monthly_sales_points,
            recent_published_count=recent_published_count,
            average_paid_price=average_paid_price,
            latest_published_at=latest_published_at,
            top_categories=top_categories,
            top_note=top_note,
        )

    except Exception as exc:
        logger.exception("Failed to compute note metrics for user %s", user_id)
        return NoteMetricsResponse(
            total_notes=0,
            published_notes=0,
            draft_notes=0,
            paid_notes=0,
            free_notes=0,
            total_sales_count=0,
            total_sales_points=0,
            monthly_sales_count=0,
            monthly_sales_points=0,
            recent_published_count=0,
            average_paid_price=0,
            latest_published_at=None,
            top_categories=[],
            top_note=None,
        )


@router.get("/public", response_model=PublicNoteListResponse)
async def list_public_notes(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, min_length=1),
    categories: Optional[List[str]] = Query(None),
    author_username: Optional[str] = Query(None, min_length=1, max_length=120),
):
    supabase = get_supabase()

    target_author_id: Optional[str] = None
    if author_username:
        user_response = (
            supabase
            .table("users")
            .select("id")
            .eq("username", author_username)
            .single()
            .execute()
        )
        if not user_response.data:
            return PublicNoteListResponse(data=[], total=0, limit=limit, offset=offset)
        target_author_id = user_response.data.get("id")

    query = (
        supabase
        .table("notes")
        .select(
            "id,title,slug,cover_image_url,excerpt,is_paid,price_points,price_jpy,allow_point_purchase,allow_jpy_purchase,tax_rate,tax_inclusive,published_at,categories,allow_share_unlock,official_share_tweet_id,official_share_tweet_url,official_share_x_username,users(username)",
            count="exact"
        )
        .eq("status", "published")
        .order("published_at", desc=True)
        .range(offset, offset + limit - 1)
    )

    if search:
        ilike_pattern = f"%{search}%"
        query = query.ilike("title", ilike_pattern)

    if categories:
        filtered = [c.strip() for c in categories if isinstance(c, str) and c.strip()]
        if filtered:
            query = query.contains("categories", filtered)

    if target_author_id:
        query = query.eq("author_id", target_author_id)

    response = query.execute()
    items: List[PublicNoteSummary] = []
    for record in response.data or []:
        user = (record.get("users") or {})
        items.append(
            PublicNoteSummary(
                id=record["id"],
                title=record.get("title", ""),
                slug=record.get("slug", ""),
                cover_image_url=record.get("cover_image_url"),
                excerpt=record.get("excerpt"),
                is_paid=bool(record.get("is_paid")),
                price_points=int(record.get("price_points") or 0),
                price_jpy=int(record.get("price_jpy")) if record.get("price_jpy") is not None else None,
                allow_point_purchase=bool(record.get("allow_point_purchase", True)),
                allow_jpy_purchase=bool(record.get("allow_jpy_purchase", False)),
                tax_rate=_coerce_float(record.get("tax_rate")),
                tax_inclusive=bool(record.get("tax_inclusive", True)),
                author_username=user.get("username"),
                published_at=record.get("published_at"),
                categories=list(record.get("categories") or []),
                allow_share_unlock=bool(record.get("allow_share_unlock", False)),
                official_share_tweet_id=record.get("official_share_tweet_id"),
                official_share_tweet_url=record.get("official_share_tweet_url"),
                official_share_x_username=record.get("official_share_x_username"),
            )
        )

    total = getattr(response, "count", None) or len(items)
    return PublicNoteListResponse(data=items, total=total, limit=limit, offset=offset)


@router.get("/public/{slug}", response_model=PublicNoteDetailResponse)
async def get_public_note(
    slug: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    supabase = get_supabase()
    user_id = get_optional_user_id(credentials)

    response = (
        supabase
        .table("notes")
        .select("*, users(username)")
        .eq("slug", slug)
        .eq("status", "published")
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="記事が見つかりません")

    note = response.data
    user = note.get("users") or {}
    salon_ids = _fetch_note_salon_ids(supabase, note["id"])

    has_access = False
    if not note.get("is_paid"):
        has_access = True
    elif user_id:
        if note.get("author_id") == user_id:
            has_access = True
        else:
            has_access = _user_has_purchased(supabase, note["id"], user_id)
            if not has_access:
                has_access = _user_has_active_salon_access(supabase, user_id, salon_ids)

    content_blocks = note.get("content_blocks") or []
    visible_blocks: List[Any] = []
    for block in content_blocks:
        access = block.get("access", "public")
        if access != "paid" or has_access:
            visible_blocks.append(block)

    return PublicNoteDetailResponse(
        id=note["id"],
        title=note.get("title", ""),
        slug=note.get("slug", ""),
        author_id=note.get("author_id"),
        author_username=user.get("username"),
        cover_image_url=note.get("cover_image_url"),
        excerpt=note.get("excerpt"),
        is_paid=bool(note.get("is_paid")),
        price_points=int(note.get("price_points") or 0),
        price_jpy=int(note.get("price_jpy")) if note.get("price_jpy") is not None else None,
        allow_point_purchase=bool(note.get("allow_point_purchase", True)),
        allow_jpy_purchase=bool(note.get("allow_jpy_purchase", False)),
        tax_rate=_coerce_float(note.get("tax_rate")),
        tax_inclusive=bool(note.get("tax_inclusive", True)),
        has_access=has_access,
        content_blocks=visible_blocks,
        published_at=note.get("published_at"),
        categories=list(note.get("categories") or []),
        allow_share_unlock=bool(note.get("allow_share_unlock", False)),
        official_share_tweet_id=note.get("official_share_tweet_id"),
        official_share_tweet_url=note.get("official_share_tweet_url"),
        official_share_x_username=note.get("official_share_x_username"),
        salon_access_ids=salon_ids,
    )


@router.get("/{note_id}", response_model=NoteDetailResponse)
async def get_note_detail(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    response = (
        supabase
        .table("notes")
        .select("*")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    ensure_note_access(response.data, user_id)
    salon_ids = _fetch_note_salon_ids(supabase, note_id)
    return map_note_detail(response.data, salon_ids=salon_ids)


@router.put("/{note_id}", response_model=NoteDetailResponse)
async def update_note(
    note_id: str,
    data: NoteUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    existing_response = (
        supabase
        .table("notes")
        .select("*")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not existing_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note = existing_response.data
    ensure_note_access(note, user_id)

    update_data: Dict[str, Any] = {"updated_at": datetime.utcnow().isoformat()}

    if data.title and data.title != note.get("title"):
        update_data["title"] = data.title
        if note.get("status") == "draft":
            base_slug = normalize_slug(data.title)
            update_data["slug"] = generate_unique_slug(supabase, base_slug, exclude_note_id=note_id)

    if data.cover_image_url is not None:
        update_data["cover_image_url"] = data.cover_image_url

    if data.excerpt is not None:
        update_data["excerpt"] = data.excerpt

    if data.content_blocks is not None:
        if not data.content_blocks:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="content_blocks は空にできません")
        update_data["content_blocks"] = [block.model_dump() for block in data.content_blocks]

    target_is_paid = bool(note.get("is_paid"))
    if data.is_paid is not None:
        target_is_paid = data.is_paid

    allow_point_purchase = bool(note.get("allow_point_purchase", True))
    if data.allow_point_purchase is not None:
        allow_point_purchase = data.allow_point_purchase

    allow_jpy_purchase = bool(note.get("allow_jpy_purchase", False))
    if data.allow_jpy_purchase is not None:
        allow_jpy_purchase = data.allow_jpy_purchase

    if not target_is_paid:
        allow_point_purchase = False
        allow_jpy_purchase = False

    if target_is_paid and not (allow_point_purchase or allow_jpy_purchase):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="有料記事には決済手段を1つ以上有効にしてください"
        )

    if allow_point_purchase:
        price_points = data.price_points if data.price_points is not None else note.get("price_points")
        if price_points is None or price_points <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ポイント決済を有効にする場合は price_points を設定してください"
            )
        update_data["price_points"] = price_points
    else:
        update_data["price_points"] = 0

    if allow_jpy_purchase:
        price_jpy = data.price_jpy if data.price_jpy is not None else note.get("price_jpy")
        if price_jpy is None or price_jpy <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="日本円決済を有効にする場合は price_jpy を設定してください"
            )
        update_data["price_jpy"] = price_jpy
    else:
        update_data["price_jpy"] = None

    final_is_paid = bool(target_is_paid and (allow_point_purchase or allow_jpy_purchase))
    update_data["is_paid"] = final_is_paid
    update_data["allow_point_purchase"] = allow_point_purchase
    update_data["allow_jpy_purchase"] = allow_jpy_purchase

    if data.categories is not None:
        update_data["categories"] = data.categories

    response = supabase.table("notes").update(update_data).eq("id", note_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ノートの更新に失敗しました")
    updated_note = response.data[0]

    if data.salon_ids is not None:
        salon_ids = _sync_note_salon_access(supabase, note_id, user_id, data.salon_ids)
    else:
        salon_ids = _fetch_note_salon_ids(supabase, note_id)

    return map_note_detail(updated_note, salon_ids=salon_ids)


@router.get("/{note_id}/official-share", response_model=OfficialShareConfigResponse)
async def get_official_share_config(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    note_response = (
        supabase
        .table("notes")
        .select("*")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not note_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note = note_response.data
    ensure_note_access(note, user_id)

    return OfficialShareConfigResponse(
        note_id=note_id,
        tweet_id=note.get("official_share_tweet_id"),
        tweet_url=note.get("official_share_tweet_url"),
        author_x_user_id=note.get("official_share_x_user_id"),
        author_x_username=note.get("official_share_x_username"),
        configured_at=note.get("official_share_set_at"),
    )


@router.post("/{note_id}/official-share", response_model=OfficialShareConfigResponse)
async def set_official_share_config(
    note_id: str,
    payload: OfficialShareSetupRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    from app.services.x_api import XAPIClient, XAPIError

    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    note_response = (
        supabase
        .table("notes")
        .select("*")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not note_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note = note_response.data
    ensure_note_access(note, user_id)

    if not note.get("is_paid"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有料NOTEのみ設定できます")

    if not note.get("allow_share_unlock"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="シェア解放を有効にしてください")

    tweet_id = payload.tweet_id or extract_tweet_id(payload.tweet_url)
    if not tweet_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有効なツイートIDまたはURLを指定してください")

    x_connection = (
        supabase
        .table("user_x_connections")
        .select("access_token, x_user_id, x_username")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    if not x_connection or not x_connection.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X連携が必要です。設定画面でXアカウントを連携してください。"
        )

    access_token = x_connection.data["access_token"]
    x_client = XAPIClient(access_token)

    try:
        tweet_info = await x_client.get_tweet(tweet_id)
    except XAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ツイートの検証に失敗しました: {str(exc)}"
        ) from exc

    author_id = tweet_info.get("author_id")
    if author_id != x_connection.data.get("x_user_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このツイートは連携済みXアカウントの投稿ではありません"
        )

    update_data = {
        "official_share_tweet_id": tweet_info.get("tweet_id"),
        "official_share_tweet_url": tweet_info.get("tweet_url"),
        "official_share_x_user_id": tweet_info.get("author_id"),
        "official_share_x_username": tweet_info.get("author_username"),
        "official_share_set_at": datetime.utcnow().isoformat(),
    }

    update_response = (
        supabase
        .table("notes")
        .update(update_data)
        .eq("id", note_id)
        .execute()
    )

    if not update_response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="公式ポスト設定の更新に失敗しました")

    return OfficialShareConfigResponse(
        note_id=note_id,
        tweet_id=tweet_info.get("tweet_id"),
        tweet_url=tweet_info.get("tweet_url"),
        tweet_text=tweet_info.get("text"),
        author_x_user_id=tweet_info.get("author_id"),
        author_x_username=tweet_info.get("author_username"),
        configured_at=update_data["official_share_set_at"],
    )


@router.delete("/{note_id}/official-share", status_code=status.HTTP_204_NO_CONTENT)
async def clear_official_share_config(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    note_response = (
        supabase
        .table("notes")
        .select("id, author_id")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not note_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    ensure_note_access(note_response.data, user_id)

    supabase.table("notes").update({
        "official_share_tweet_id": None,
        "official_share_tweet_url": None,
        "official_share_x_user_id": None,
        "official_share_x_username": None,
        "official_share_set_at": None,
    }).eq("id", note_id).execute()

    return None


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    response = (
        supabase
        .table("notes")
        .select("author_id")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    ensure_note_access(response.data, user_id)
    supabase.table("notes").delete().eq("id", note_id).execute()
    return None


@router.post("/{note_id}/publish", response_model=NoteDetailResponse)
async def publish_note(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    existing = (
        supabase
        .table("notes")
        .select("*")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note = existing.data
    ensure_note_access(note, user_id)

    if note.get("is_paid") and (note.get("price_points") is None or note.get("price_points") <= 0):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有料記事の価格を設定してください")

    base_slug = normalize_slug(note.get("title", ""))
    slug = generate_unique_slug(supabase, base_slug, exclude_note_id=note_id)

    update_data = {
        "status": "published",
        "slug": slug,
        "published_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    response = supabase.table("notes").update(update_data).eq("id", note_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ノートの公開に失敗しました")
    salon_ids = _fetch_note_salon_ids(supabase, note_id)

    return map_note_detail(response.data[0], salon_ids=salon_ids)


@router.post("/{note_id}/unpublish", response_model=NoteDetailResponse)
async def unpublish_note(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    existing = (
        supabase
        .table("notes")
        .select("*")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note = existing.data
    ensure_note_access(note, user_id)

    response = (
        supabase
        .table("notes")
        .update({
            "status": "draft",
            "published_at": None,
            "updated_at": datetime.utcnow().isoformat(),
        })
        .eq("id", note_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ノートの非公開化に失敗しました")
    salon_ids = _fetch_note_salon_ids(supabase, note_id)

    return map_note_detail(response.data[0], salon_ids=salon_ids)


def _user_has_purchased(supabase: Client, note_id: str, user_id: str) -> bool:
    purchase_response = (
        supabase
        .table("note_purchases")
        .select("id, expires_at")
        .eq("note_id", note_id)
        .eq("buyer_id", user_id)
        .limit(1)
        .execute()
    )
    
    if not purchase_response.data:
        return False
    
    purchase = purchase_response.data[0]
    
    # expires_atがない場合は永久アクセス（通常購入）
    if not purchase.get("expires_at"):
        return True
    
    # expires_atがある場合は期限をチェック
    expires_at = datetime.fromisoformat(purchase["expires_at"].replace("Z", "+00:00"))
    return datetime.utcnow().replace(tzinfo=timezone.utc) < expires_at


@router.post("/{note_id}/purchase", response_model=NotePurchaseResponse, status_code=status.HTTP_201_CREATED)
async def purchase_note(
    note_id: str,
    payment_method: Literal["points", "yen"] = Query("points"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()

    if not hasattr(supabase, "table") and payment_method == "points":
        return _purchase_note_via_rpc(supabase, note_id, user_id)

    user_response = (
        supabase
        .table("users")
        .select("email, username, point_balance")
        .eq("id", user_id)
        .single()
        .execute()
    )

    if not user_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")

    user_record = user_response.data

    note_response = (
        supabase
        .table("notes")
        .select("id, author_id, is_paid, price_points, price_jpy, allow_point_purchase, allow_jpy_purchase, slug, title")
        .eq("id", note_id)
        .single()
        .execute()
    )

    if not note_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ノートが見つかりません")

    note_record = note_response.data
    salon_ids = _fetch_note_salon_ids(supabase, note_id)

    if note_record.get("author_id") == user_id or not note_record.get("is_paid"):
        purchased_at = datetime.utcnow().isoformat()
        return NotePurchaseResponse(
            note_id=note_id,
            points_spent=0,
            remaining_points=int(user_record.get("point_balance", 0)),
            purchased_at=purchased_at,
            payment_method="points",
            payment_status="completed",
        )

    if salon_ids and _user_has_active_salon_access(supabase, user_id, salon_ids):
        purchased_at = datetime.utcnow().isoformat()
        try:
            supabase.table("note_purchases").insert(
                {
                    "note_id": note_id,
                    "buyer_id": user_id,
                    "points_spent": 0,
                    "purchased_at": purchased_at,
                }
            ).execute()
        except Exception:
            pass

        return NotePurchaseResponse(
            note_id=note_id,
            points_spent=0,
            remaining_points=int(user_record.get("point_balance", 0)),
            purchased_at=purchased_at,
            payment_method="points",
            payment_status="completed",
        )

    if payment_method == "points":
        if not note_record.get("allow_point_purchase", True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このNOTEはポイント決済に対応していません"
            )
        if not hasattr(supabase, "table"):
            return _purchase_note_via_rpc(supabase, note_id, user_id)
        return _purchase_note_via_rpc(supabase, note_id, user_id)

    if payment_method != "yen":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="サポートされていない決済方法です")

    if not note_record.get("allow_jpy_purchase"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このNOTEは日本円決済に対応していません"
        )

    price_jpy = note_record.get("price_jpy")
    if price_jpy is None or price_jpy <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="price_jpy が設定されていません")

    amount_jpy = int(price_jpy)
    amount_usd = round(amount_jpy / JPY_TO_USD_RATE, 2)
    external_id = f"note_yen_{note_id}_{uuid.uuid4().hex[:8]}"

    backend_url = settings.backend_public_url.rstrip("/")
    frontend_url = settings.frontend_url.rstrip("/")
    webhook_url = f"{backend_url}/api/webhooks/one-lat"
    slug = note_record.get("slug")
    success_path = f"/notes/{slug}/purchase/success" if slug else "/notes/purchase/success"
    error_path = f"/notes/{slug}/purchase/error" if slug else "/notes/purchase/error"
    success_url = f"{frontend_url}{success_path}?external_id={external_id}"
    error_url = f"{frontend_url}{error_path}?external_id={external_id}"

    checkout_data = await one_lat_client.create_checkout_preference(
        amount=amount_usd,
        currency="USD",
        title=f"Note Purchase - {note_record.get('title', 'NOTE')}",
        external_id=external_id,
        webhook_url=webhook_url,
        success_url=success_url,
        error_url=error_url,
        payer_email=user_record.get("email"),
        payer_name=user_record.get("username"),
    )

    metadata = {
        "note_slug": slug,
        "author_id": note_record.get("author_id"),
    }

    order_payload = {
        "user_id": user_id,
        "seller_id": note_record.get("author_id"),
        "item_type": "note",
        "item_id": note_id,
        "payment_method": "yen",
        "currency": "JPY",
        "amount_jpy": amount_jpy,
        "tax_amount_jpy": 0,
        "status": "PENDING",
        "external_id": external_id,
        "checkout_preference_id": checkout_data.get("id"),
        "metadata": metadata,
    }

    order_response = supabase.table("payment_orders").insert(order_payload).execute()
    if not order_response.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="注文情報の作成に失敗しました"
        )

    order_row = order_response.data[0]

    return NotePurchaseResponse(
        note_id=note_id,
        points_spent=0,
        amount_jpy=amount_jpy,
        remaining_points=int(user_record.get("point_balance", 0)),
        payment_method="yen",
        payment_status="pending",
        purchased_at=datetime.utcnow(),
        checkout_url=checkout_data.get("checkout_url"),
        external_id=external_id,
    )


# ========================================
# X (Twitter) Share to Unlock
# ========================================

@router.post("/{note_id}/share", status_code=status.HTTP_200_OK)
async def share_note_to_x(
    note_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    NOTEをXでリツイートして無料解放
    
    Flow:
    1. NOTE存在確認 & シェア許可確認
    2. シェア済みチェック
    3. X連携確認
    4. 不正検知チェック
    5. 公式ポストをリツイート
    6. リツイート検証
    7. アクセス権付与
    8. 著者に即時ポイント報酬付与
    
    Returns:
        {
            "message": "リツイートが完了しました",
            "tweet_url": "https://x.com/username/status/123",
            "has_access": true,
            "author_reward_points": 1
        }
    """
    from app.services.x_api import XAPIClient, XAPIError
    from app.services.fraud_detection import FraudDetector
    from app.services.share_rewards import ShareRewardService
    
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    
    # IPアドレス取得
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")
    
    try:
        # 1. NOTE存在確認 & シェア許可確認
        note_response = supabase.table("notes").select(
            "id, title, slug, author_id, is_paid, allow_share_unlock, "
            "official_share_tweet_id, official_share_tweet_url, "
            "official_share_x_user_id, official_share_x_username"
        ).eq("id", note_id).eq("status", "published").maybe_single().execute()
        
        if not note_response or not note_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="NOTEが見つかりません"
            )
        
        note = note_response.data
        
        if not note.get("is_paid"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このNOTEは無料です"
            )
        
        if not note.get("allow_share_unlock"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このNOTEはシェア解放が許可されていません"
            )
        
        official_tweet_id = note.get("official_share_tweet_id")
        official_author_id = note.get("official_share_x_user_id")
        official_tweet_url = note.get("official_share_tweet_url")
        official_author_username = note.get("official_share_x_username")

        if not official_tweet_id or not official_author_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このNOTEには公式リツイート対象が設定されていません"
            )

        # 自分の記事はシェアできない
        if note["author_id"] == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="自分のNOTEはシェアできません"
            )
        
        # 2. 既にシェア済みかチェック
        existing_share = supabase.table("note_shares").select("id").eq(
            "note_id", note_id
        ).eq("user_id", user_id).maybe_single().execute()
        
        if existing_share and existing_share.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="既にこのNOTEをシェア済みです"
            )
        
        # 3. X連携確認
        x_connection = supabase.table("user_x_connections").select(
            "access_token, x_user_id, x_username, account_created_at, followers_count, is_verified"
        ).eq("user_id", user_id).maybe_single().execute()
        
        if not x_connection or not x_connection.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X連携が必要です。設定画面でXアカウントを連携してください。"
            )
        
        access_token = x_connection.data["access_token"]
        x_info = x_connection.data
        
        # 4. 不正検知チェック
        fraud_detector = FraudDetector(supabase)
        
        fraud_data = {
            "user_id": user_id,
            "ip_address": ip_address,
            "account_created_at": x_info.get("account_created_at"),
            "followers_count": x_info.get("followers_count", 0),
            "is_verified": x_info.get("is_verified", False)
        }
        
        fraud_score, severity = await fraud_detector.calculate_fraud_score(fraud_data)
        is_suspicious = fraud_score >= 30  # MEDIUM以上を疑わしいとする
        
        # 5. 公式ポストをリツイート
        x_client = XAPIClient(access_token)

        buyer_x_user_id = x_info.get("x_user_id")
        buyer_username = x_info.get("x_username")

        if not buyer_x_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Xアカウント情報の取得に失敗しました。再連携をお試しください。"
            )

        try:
            await x_client.retweet(buyer_x_user_id, official_tweet_id)
        except XAPIError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"リツイートに失敗しました: {str(e)}"
            )

        # 6. リツイート検証
        retweet_info = await x_client.verify_retweet(buyer_x_user_id, official_tweet_id)
        is_verified = retweet_info is not None
        retweet_id = retweet_info.get("retweet_id") if retweet_info else None
        retweet_url = None
        if retweet_id and buyer_username:
            retweet_url = f"https://x.com/{buyer_username}/status/{retweet_id}"

        canonical_tweet_url = official_tweet_url
        if not canonical_tweet_url and official_author_username:
            canonical_tweet_url = f"https://x.com/{official_author_username}/status/{official_tweet_id}"
        if not canonical_tweet_url:
            canonical_tweet_url = f"https://x.com/i/web/status/{official_tweet_id}"

        # 7. note_sharesレコード作成
        share_data = {
            "note_id": note_id,
            "user_id": user_id,
            "tweet_id": official_tweet_id,
            "tweet_url": canonical_tweet_url,
            "retweet_tweet_id": retweet_id,
            "retweet_url": retweet_url,
            "verified": is_verified,
            "verified_at": datetime.utcnow().isoformat() if is_verified else None,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "is_suspicious": is_suspicious
        }
        
        share_response = supabase.table("note_shares").insert(share_data).execute()
        
        if not share_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="シェア記録の作成に失敗しました"
            )
        
        share_record = share_response.data[0] if isinstance(share_response.data, list) else share_response.data
        share_id = share_record["id"]
        
        # 7.5. アクセス権を付与（note_purchasesテーブルに追加）
        # シェアによるアクセスは7日間有効
        expires_at = datetime.utcnow() + timedelta(days=7)
        purchase_data = {
            "note_id": note_id,
            "buyer_id": user_id,  # note_purchasesテーブルはbuyer_idカラムを使用
            "points_spent": 0,  # シェアなのでポイント消費なし
            "purchased_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat()
        }
        
        try:
            supabase.table("note_purchases").insert(purchase_data).execute()
        except Exception as e:
            logger.warning(f"Failed to create note_purchase record (might already exist): {e}")
        
        # 8. 不正疑いがある場合はアラート生成
        if is_suspicious:
            await fraud_detector.create_alert(
                alert_type="suspicious_share_pattern",
                note_share_id=share_id,
                note_id=note_id,
                user_id=user_id,
                severity=severity,
                description=f"不正スコア: {fraud_score} - 手動確認が必要です"
            )
        
        # 9. ポイント報酬付与（不正スコアが高い場合は保留）
        reward_service = ShareRewardService(supabase)
        reward_points = 0
        
        should_block = await fraud_detector.should_block_reward(fraud_score)
        
        if not should_block:
            # 報酬レート取得
            reward_rate = await reward_service.get_current_reward_rate()
            
            # 著者にポイント付与
            reward_result = await reward_service.grant_share_reward(
                author_id=note["author_id"],
                note_id=note_id,
                shared_by_user_id=user_id,
                points_amount=reward_rate,
                share_id=share_id
            )
            
            if reward_result:
                reward_points = reward_result["points_granted"]
        else:
            logger.warning(
                f"Share reward blocked due to high fraud score: "
                f"score={fraud_score}, share_id={share_id}"
            )
        
        return {
            "message": "リツイートが完了しました",
            "tweet_url": retweet_url or canonical_tweet_url,
            "has_access": True,
            "author_reward_points": reward_points,
            "note_id": note_id,
            "share_id": share_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Share to X failed: note_id={note_id}, user_id={user_id}, error={str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"シェア処理に失敗しました。もう一度お試しください。"
        )


@router.get("/{note_id}/share-status")
async def get_share_status(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    ユーザーのシェア状態確認
    
    Returns:
        {
            "has_shared": bool,
            "tweet_url": str | null,
            "shared_at": str | null
        }
    """
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    
    try:
        share_response = supabase.table("note_shares").select(
            "tweet_url, retweet_url, shared_at, verified"
        ).eq("note_id", note_id).eq("user_id", user_id).maybe_single().execute()
        
        if share_response and share_response.data:
            return {
                "has_shared": True,
                "tweet_url": share_response.data.get("retweet_url") or share_response.data.get("tweet_url"),
                "retweet_url": share_response.data.get("retweet_url"),
                "shared_at": share_response.data.get("shared_at"),
                "verified": share_response.data.get("verified", False)
            }
        else:
            return {
                "has_shared": False,
                "tweet_url": None,
                "retweet_url": None,
                "shared_at": None,
                "verified": False
            }
    
    except Exception as e:
        logger.error(f"Failed to get share status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="シェア状態の取得に失敗しました"
        )


@router.get("/{note_id}/share-stats")
async def get_share_stats(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    NOTE全体のシェア統計（著者向け）
    
    Returns:
        {
            "total_shares": int,
            "total_reward_points": int,
            "verified_shares": int,
            "suspicious_shares": int
        }
    """
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    
    try:
        # NOTE存在確認 & 著者確認
        note_response = supabase.table("notes").select(
            "id, author_id"
        ).eq("id", note_id).maybe_single().execute()
        
        if not note_response or not note_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="NOTEが見つかりません"
            )
        
        if note_response.data["author_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="このNOTEの統計情報を閲覧する権限がありません"
            )
        
        # シェア統計取得
        shares_response = supabase.table("note_shares").select(
            "id, verified, is_suspicious, points_amount"
        ).eq("note_id", note_id).execute()
        
        shares = shares_response.data if shares_response and shares_response.data else []
        
        total_shares = len(shares)
        verified_shares = sum(1 for s in shares if s.get("verified"))
        suspicious_shares = sum(1 for s in shares if s.get("is_suspicious"))
        total_reward_points = sum(s.get("points_amount", 0) for s in shares)
        
        return {
            "total_shares": total_shares,
            "total_reward_points": total_reward_points,
            "verified_shares": verified_shares,
            "suspicious_shares": suspicious_shares
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get share stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="シェア統計の取得に失敗しました"
        )
