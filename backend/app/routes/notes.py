from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, status, Depends, Query
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
)
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/notes", tags=["notes"])
security = HTTPBearer(auto_error=False)


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


@router.get("/public", response_model=PublicNoteListResponse)
async def list_public_notes(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, min_length=1),
    categories: Optional[List[str]] = Query(None),
    author_username: Optional[str] = Query(None, min_length=1, max_length=120),
):
    supabase = get_supabase()

    select_columns = "id,title,slug,cover_image_url,excerpt,is_paid,price_points,published_at,categories,users(username)"
    if author_username:
        select_columns = "id,title,slug,cover_image_url,excerpt,is_paid,price_points,published_at,categories,users!inner(username)"

    query = (
        supabase
        .table("notes")
        .select(select_columns, count="exact")
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

    if author_username:
        query = query.eq("users.username", author_username)

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
