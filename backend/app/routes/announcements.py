import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/announcements", tags=["announcements"])


def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


class AnnouncementPublicSchema(BaseModel):
    id: str
    title: str
    summary: str
    body: str
    highlight: bool
    published_at: str


class AnnouncementListResponse(BaseModel):
    data: List[AnnouncementPublicSchema]


def serialize_announcement(row) -> AnnouncementPublicSchema:
    published_at = row.get("published_at")
    if not published_at:
        created_at = row.get("created_at")
        if created_at:
            published_at = created_at
        else:
            published_at = datetime.now(timezone.utc).isoformat()
    return AnnouncementPublicSchema(
        id=str(row.get("id")),
        title=row.get("title", ""),
        summary=row.get("summary", ""),
        body=row.get("body", ""),
        highlight=bool(row.get("highlight", False)),
        published_at=published_at,
    )


@router.get("", response_model=AnnouncementListResponse)
async def list_public_announcements(
    limit: int = Query(6, ge=1, le=20),
):
    try:
        supabase = get_supabase()
        response = (
            supabase
            .table("announcements")
            .select("id, title, summary, body, highlight, published_at, created_at, is_published")
            .eq("is_published", True)
            .order("published_at", desc=True)
            .limit(limit)
            .execute()
        )
        if getattr(response, "error", None):
            message = getattr(response.error, "message", None) or str(response.error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"お知らせの取得に失敗しました: {message}",
            )
        rows = response.data or []
        announcements = [serialize_announcement(row) for row in rows]
        return AnnouncementListResponse(data=announcements)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch public announcements")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"お知らせの取得に失敗しました: {exc}",
        )


@router.get("/{announcement_id}", response_model=AnnouncementPublicSchema)
async def get_announcement_detail(announcement_id: str):
    try:
        supabase = get_supabase()
        response = (
            supabase
            .table("announcements")
            .select("id, title, summary, body, highlight, published_at, created_at, is_published")
            .eq("id", announcement_id)
            .single()
            .execute()
        )
        if getattr(response, "error", None):
            message = getattr(response.error, "message", None) or str(response.error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"お知らせの取得に失敗しました: {message}",
            )
        if not response.data or (response.data.get("is_published") is False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたお知らせが見つかりません",
            )
        return serialize_announcement(response.data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch announcement detail")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"お知らせの取得に失敗しました: {exc}",
        )
