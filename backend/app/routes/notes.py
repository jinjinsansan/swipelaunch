from __future__ import annotations

import logging
import re
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

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
)
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/notes", tags=["notes"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


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
        status=record.get("status", "draft"),
        published_at=record.get("published_at"),
        updated_at=record.get("updated_at"),
        categories=list(record.get("categories") or []),
    )


def map_note_detail(record: Dict[str, Any]) -> NoteDetailResponse:
    summary = map_note_summary(record)
    content_blocks = record.get("content_blocks") or []
    return NoteDetailResponse(**summary.dict(), content_blocks=content_blocks)


def ensure_note_access(note: Dict[str, Any], user_id: str) -> None:
    if note.get("author_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このノートにアクセスする権限がありません",
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

    note_data = {
        "author_id": user_id,
        "title": data.title,
        "slug": slug,
        "cover_image_url": data.cover_image_url,
        "excerpt": data.excerpt,
        "content_blocks": [block.model_dump() for block in data.content_blocks],
        "is_paid": data.is_paid,
        "price_points": data.price_points or 0,
        "status": "draft",
        "categories": data.categories,
    }

    response = supabase.table("notes").insert(note_data).execute()
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ノートの作成に失敗しました",
        )

    return map_note_detail(response.data[0])


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
        .select("id,title,slug,cover_image_url,excerpt,is_paid,price_points,published_at,categories,users(username)", count="exact")
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
                author_username=user.get("username"),
                published_at=record.get("published_at"),
                categories=list(record.get("categories") or []),
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

    has_access = False
    if not note.get("is_paid"):
        has_access = True
    elif user_id:
        if note.get("author_id") == user_id:
            has_access = True
        else:
            has_access = _user_has_purchased(supabase, note["id"], user_id)

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
        has_access=has_access,
        content_blocks=visible_blocks,
        published_at=note.get("published_at"),
        categories=list(note.get("categories") or []),
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
    return map_note_detail(response.data)


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

    if data.is_paid is not None:
        update_data["is_paid"] = data.is_paid
        if data.is_paid:
            price = data.price_points if data.price_points is not None else note.get("price_points", 0)
            if not price or price <= 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有料記事の価格を設定してください")
            update_data["price_points"] = price
        else:
            update_data["price_points"] = 0
    elif data.price_points is not None:
        if note.get("is_paid") and data.price_points == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有料記事の価格は1ポイント以上です")
        update_data["price_points"] = data.price_points

    if data.categories is not None:
        update_data["categories"] = data.categories

    response = supabase.table("notes").update(update_data).eq("id", note_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ノートの更新に失敗しました")

    return map_note_detail(response.data[0])


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

    return map_note_detail(response.data[0])


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

    return map_note_detail(response.data[0])


def _user_has_purchased(supabase: Client, note_id: str, user_id: str) -> bool:
    purchase_response = (
        supabase
        .table("note_purchases")
        .select("id")
        .eq("note_id", note_id)
        .eq("buyer_id", user_id)
        .limit(1)
        .execute()
    )
    return bool(purchase_response.data)


@router.post("/{note_id}/purchase", response_model=NotePurchaseResponse, status_code=status.HTTP_201_CREATED)
async def purchase_note(
    note_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
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
    )


# ========================================
# X (Twitter) Share to Unlock
# ========================================

@router.post("/notes/{note_id}/share", status_code=status.HTTP_200_OK)
async def share_note_to_x(
    note_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    NOTEをXでシェアして無料解放
    
    Flow:
    1. X連携確認
    2. 不正検知チェック
    3. Xにツイート投稿
    4. ツイート検証
    5. アクセス権付与
    6. 著者に即時ポイント報酬付与
    
    Returns:
        {
            "message": "シェアが完了しました",
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
            "id, title, slug, author_id, is_paid, allow_share_unlock"
        ).eq("id", note_id).eq("status", "published").single().execute()
        
        if not note_response.data:
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
        
        if existing_share.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="既にこのNOTEをシェア済みです"
            )
        
        # 3. X連携確認
        x_connection = supabase.table("user_x_connections").select(
            "access_token, x_user_id, x_username, account_created_at, followers_count, is_verified"
        ).eq("user_id", user_id).maybe_single().execute()
        
        if not x_connection.data:
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
        
        # 5. Xにツイート投稿
        x_client = XAPIClient(access_token)
        
        # ツイート本文生成
        note_url = f"https://d-swipe.com/notes/{note['slug']}"
        tweet_text = f"{note['title']} | D-swipe {note_url} #Dswipe #NOTE"
        
        try:
            tweet_result = await x_client.post_tweet(tweet_text)
        except XAPIError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"ツイート投稿に失敗しました: {str(e)}"
            )
        
        tweet_id = tweet_result["tweet_id"]
        tweet_url = f"https://x.com/{x_info['x_username']}/status/{tweet_id}"
        
        # 6. ツイート検証
        try:
            is_verified = await x_client.verify_tweet(tweet_id, note_url)
        except XAPIError:
            is_verified = True  # 検証失敗時は一旦許可（後で手動確認）
        
        # 7. note_sharesレコード作成
        share_data = {
            "note_id": note_id,
            "user_id": user_id,
            "tweet_id": tweet_id,
            "tweet_url": tweet_url,
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
            "message": "シェアが完了しました",
            "tweet_url": tweet_url,
            "has_access": True,
            "author_reward_points": reward_points,
            "note_id": note_id,
            "share_id": share_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Share to X failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"シェア処理に失敗しました: {str(e)}"
        )


@router.get("/notes/{note_id}/share-status")
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
            "tweet_url, shared_at, verified"
        ).eq("note_id", note_id).eq("user_id", user_id).maybe_single().execute()
        
        if share_response.data:
            return {
                "has_shared": True,
                "tweet_url": share_response.data.get("tweet_url"),
                "shared_at": share_response.data.get("shared_at"),
                "verified": share_response.data.get("verified", False)
            }
        else:
            return {
                "has_shared": False,
                "tweet_url": None,
                "shared_at": None,
                "verified": False
            }
    
    except Exception as e:
        logger.error(f"Failed to get share status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="シェア状態の取得に失敗しました"
        )


@router.get("/notes/{note_id}/share-stats")
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
        ).eq("id", note_id).single().execute()
        
        if not note_response.data:
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
        
        shares = shares_response.data if shares_response.data else []
        
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
