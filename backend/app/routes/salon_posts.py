"""Salon community feed endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salon_posts import (
    SalonCommentCreateRequest,
    SalonCommentListResponse,
    SalonCommentResponse,
    SalonCommentUpdateRequest,
    SalonPostCreateRequest,
    SalonPostLikeResponse,
    SalonPostListResponse,
    SalonPostResponse,
    SalonPostUpdateRequest,
)
from app.utils.auth import decode_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/salons/{salon_id}/posts", tags=["salon-posts"])
security = HTTPBearer()


def _get_current_user(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

    supabase = get_supabase_client()
    response = (
        supabase
        .table("users")
        .select("id, username, user_type")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません")
    return response.data


def _get_salon_and_access(supabase, salon_id: str, user_id: str) -> Tuple[Dict[str, Any], bool]:
    salon_response = (
        supabase
        .table("salons")
        .select("id, owner_id")
        .eq("id", salon_id)
        .single()
        .execute()
    )
    if not salon_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")

    salon = salon_response.data
    if salon.get("owner_id") == user_id:
        return salon, True

    membership_response = (
        supabase
        .table("salon_memberships")
        .select("status")
        .eq("salon_id", salon_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    for membership in membership_response.data or []:
        if str(membership.get("status", "")).upper() == "ACTIVE":
            return salon, False

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="このサロンにアクセスする権限がありません")


def _map_post_record(
    record: Dict[str, Any],
    like_count: int,
    comment_count: int,
    liked_by_me: bool,
    author_username: str | None,
) -> SalonPostResponse:
    return SalonPostResponse(
        id=record.get("id"),
        salon_id=record.get("salon_id"),
        user_id=record.get("user_id"),
        title=record.get("title"),
        body=record.get("body", ""),
        is_pinned=bool(record.get("is_pinned", False)),
        is_published=bool(record.get("is_published", True)),
        like_count=like_count,
        comment_count=comment_count,
        liked_by_me=liked_by_me,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        author_username=author_username,
    )


def _map_comment_record(record: Dict[str, Any], author_username: str | None) -> SalonCommentResponse:
    return SalonCommentResponse(
        id=record.get("id"),
        post_id=record.get("post_id"),
        user_id=record.get("user_id"),
        body=record.get("body", ""),
        parent_id=record.get("parent_id"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        author_username=author_username,
    )


def _fetch_post_with_access(supabase, salon_id: str, post_id: str) -> Dict[str, Any]:
    response = (
        supabase
        .table("salon_posts")
        .select("*")
        .eq("id", post_id)
        .eq("salon_id", salon_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="投稿が見つかりません")
    return response.data


def _get_post_metrics(supabase, post_id: str, current_user_id: str) -> Tuple[int, int, bool]:
    like_count_resp = (
        supabase
        .table("salon_post_likes")
        .select("id", count="exact")
        .eq("post_id", post_id)
        .execute()
    )
    like_count = getattr(like_count_resp, "count", 0) or 0

    comment_count_resp = (
        supabase
        .table("salon_comments")
        .select("id", count="exact")
        .eq("post_id", post_id)
        .execute()
    )
    comment_count = getattr(comment_count_resp, "count", 0) or 0

    liked_resp = (
        supabase
        .table("salon_post_likes")
        .select("id")
        .eq("post_id", post_id)
        .eq("user_id", current_user_id)
        .limit(1)
        .execute()
    )
    liked_by_me = bool(liked_resp.data)
    return like_count, comment_count, liked_by_me


def _get_usernames(supabase, user_ids: List[str]) -> Dict[str, str]:
    if not user_ids:
        return {}
    response = (
        supabase
        .table("users")
        .select("id, username")
        .in_("id", user_ids)
        .execute()
    )
    mapping: Dict[str, str] = {}
    for row in response.data or []:
        if row.get("id"):
            mapping[row["id"]] = row.get("username")
    return mapping


@router.get("", response_model=SalonPostListResponse)
async def list_posts(
    salon_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])

    count_query = (
        supabase
        .table("salon_posts")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
    )
    if not is_owner:
        count_query = count_query.eq("is_published", True)
    count_resp = count_query.execute()
    total = getattr(count_resp, "count", 0) or 0

    range_end = offset + limit - 1
    posts_query = (
        supabase
        .table("salon_posts")
        .select("*")
        .eq("salon_id", salon_id)
        .order("is_pinned", desc=True)
        .order("created_at", desc=True)
        .range(offset, range_end)
    )
    if not is_owner:
        posts_query = posts_query.eq("is_published", True)
    posts_resp = posts_query.execute()
    records = posts_resp.data or []

    post_ids = [record.get("id") for record in records if record.get("id")]
    user_ids = [record.get("user_id") for record in records if record.get("user_id")]
    username_map = _get_usernames(supabase, user_ids)

    like_counts: Dict[str, int] = {}
    comment_counts: Dict[str, int] = {}
    liked_posts: Dict[str, bool] = {}

    if post_ids:
        likes_resp = (
            supabase
            .table("salon_post_likes")
            .select("post_id")
            .in_("post_id", post_ids)
            .execute()
        )
        for row in likes_resp.data or []:
            post_id = row.get("post_id")
            if post_id:
                like_counts[post_id] = like_counts.get(post_id, 0) + 1

        comments_resp = (
            supabase
            .table("salon_comments")
            .select("post_id")
            .in_("post_id", post_ids)
            .execute()
        )
        for row in comments_resp.data or []:
            post_id = row.get("post_id")
            if post_id:
                comment_counts[post_id] = comment_counts.get(post_id, 0) + 1

        liked_resp = (
            supabase
            .table("salon_post_likes")
            .select("post_id")
            .eq("user_id", user["id"])
            .in_("post_id", post_ids)
            .execute()
        )
        for row in liked_resp.data or []:
            post_id = row.get("post_id")
            if post_id:
                liked_posts[post_id] = True

    data = [
        _map_post_record(
            record,
            like_counts.get(record.get("id"), 0),
            comment_counts.get(record.get("id"), 0),
            liked_posts.get(record.get("id"), False),
            username_map.get(record.get("user_id")),
        )
        for record in records
    ]

    return SalonPostListResponse(data=data, total=total, limit=limit, offset=offset)


@router.post("", response_model=SalonPostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    salon_id: str,
    payload: SalonPostCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, _ = _get_salon_and_access(supabase, salon_id, user["id"])

    post_data = {
        "salon_id": salon_id,
        "user_id": user["id"],
        "title": payload.title,
        "body": payload.body,
        "is_published": payload.is_published,
    }

    response = supabase.table("salon_posts").insert(post_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="投稿の作成に失敗しました")

    record = response.data[0]
    like_count, comment_count, liked_by_me = _get_post_metrics(supabase, record["id"], user["id"])
    username_map = _get_usernames(supabase, [record.get("user_id")])
    return _map_post_record(record, like_count, comment_count, liked_by_me, username_map.get(record.get("user_id")))


@router.get("/{post_id}", response_model=SalonPostResponse)
async def get_post(
    salon_id: str,
    post_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, _ = _get_salon_and_access(supabase, salon_id, user["id"])

    record = _fetch_post_with_access(supabase, salon_id, post_id)
    like_count, comment_count, liked_by_me = _get_post_metrics(supabase, post_id, user["id"])
    username_map = _get_usernames(supabase, [record.get("user_id")])
    return _map_post_record(record, like_count, comment_count, liked_by_me, username_map.get(record.get("user_id")))


@router.patch("/{post_id}", response_model=SalonPostResponse)
async def update_post(
    salon_id: str,
    post_id: str,
    payload: SalonPostUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])

    record = _fetch_post_with_access(supabase, salon_id, post_id)
    if record.get("user_id") != user["id"] and not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="投稿を編集する権限がありません")

    update_data: Dict[str, Any] = {}
    if payload.title is not None:
        update_data["title"] = payload.title
    if payload.body is not None:
        update_data["body"] = payload.body
    if payload.is_published is not None:
        update_data["is_published"] = payload.is_published
    if payload.is_pinned is not None:
        if record.get("user_id") != user["id"] and not is_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ピン留めを変更する権限がありません")
        update_data["is_pinned"] = payload.is_pinned

    if not update_data:
        like_count, comment_count, liked_by_me = _get_post_metrics(supabase, post_id, user["id"])
        username_map = _get_usernames(supabase, [record.get("user_id")])
        return _map_post_record(record, like_count, comment_count, liked_by_me, username_map.get(record.get("user_id")))

    response = (
        supabase
        .table("salon_posts")
        .update(update_data)
        .eq("id", post_id)
        .eq("salon_id", salon_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="投稿の更新に失敗しました")

    updated = response.data[0]
    like_count, comment_count, liked_by_me = _get_post_metrics(supabase, post_id, user["id"])
    username_map = _get_usernames(supabase, [updated.get("user_id")])
    return _map_post_record(updated, like_count, comment_count, liked_by_me, username_map.get(updated.get("user_id")))


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    salon_id: str,
    post_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])

    record = _fetch_post_with_access(supabase, salon_id, post_id)
    if record.get("user_id") != user["id"] and not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="投稿を削除する権限がありません")

    supabase.table("salon_posts").delete().eq("id", post_id).eq("salon_id", salon_id).execute()


@router.get("/{post_id}/comments", response_model=SalonCommentListResponse)
async def list_comments(
    salon_id: str,
    post_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_post_with_access(supabase, salon_id, post_id)

    count_resp = (
        supabase
        .table("salon_comments")
        .select("id", count="exact")
        .eq("post_id", post_id)
        .execute()
    )
    total = getattr(count_resp, "count", 0) or 0

    range_end = offset + limit - 1
    comments_resp = (
        supabase
        .table("salon_comments")
        .select("*")
        .eq("post_id", post_id)
        .order("created_at", desc=True)
        .range(offset, range_end)
        .execute()
    )
    records = comments_resp.data or []
    user_ids = [record.get("user_id") for record in records if record.get("user_id")]
    username_map = _get_usernames(supabase, user_ids)

    data = [_map_comment_record(record, username_map.get(record.get("user_id"))) for record in records]
    return SalonCommentListResponse(data=data, total=total, limit=limit, offset=offset)


@router.post("/{post_id}/comments", response_model=SalonCommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    salon_id: str,
    post_id: str,
    payload: SalonCommentCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_post_with_access(supabase, salon_id, post_id)

    if payload.parent_id:
        parent_resp = (
            supabase
            .table("salon_comments")
            .select("id, post_id")
            .eq("id", payload.parent_id)
            .single()
            .execute()
        )
        if not parent_resp.data or parent_resp.data.get("post_id") != post_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="親コメントが見つかりません")

    comment_data = {
        "post_id": post_id,
        "user_id": user["id"],
        "body": payload.body,
        "parent_id": payload.parent_id,
    }

    response = supabase.table("salon_comments").insert(comment_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="コメントの作成に失敗しました")

    record = response.data[0]
    username_map = _get_usernames(supabase, [record.get("user_id")])
    return _map_comment_record(record, username_map.get(record.get("user_id")))


@router.patch("/{post_id}/comments/{comment_id}", response_model=SalonCommentResponse)
async def update_comment(
    salon_id: str,
    post_id: str,
    comment_id: str,
    payload: SalonCommentUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_post_with_access(supabase, salon_id, post_id)

    comment_resp = (
        supabase
        .table("salon_comments")
        .select("*")
        .eq("id", comment_id)
        .eq("post_id", post_id)
        .single()
        .execute()
    )
    if not comment_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="コメントが見つかりません")

    comment = comment_resp.data
    if comment.get("user_id") != user["id"] and not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="コメントを編集する権限がありません")

    response = (
        supabase
        .table("salon_comments")
        .update({"body": payload.body})
        .eq("id", comment_id)
        .eq("post_id", post_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="コメントの更新に失敗しました")

    updated = response.data[0]
    username_map = _get_usernames(supabase, [updated.get("user_id")])
    return _map_comment_record(updated, username_map.get(updated.get("user_id")))


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    salon_id: str,
    post_id: str,
    comment_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_post_with_access(supabase, salon_id, post_id)

    comment_resp = (
        supabase
        .table("salon_comments")
        .select("user_id")
        .eq("id", comment_id)
        .eq("post_id", post_id)
        .single()
        .execute()
    )
    if not comment_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="コメントが見つかりません")

    if comment_resp.data.get("user_id") != user["id"] and not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="コメントを削除する権限がありません")

    supabase.table("salon_comments").delete().eq("id", comment_id).eq("post_id", post_id).execute()


@router.post("/{post_id}/like", response_model=SalonPostLikeResponse)
async def toggle_like(
    salon_id: str,
    post_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])
    _fetch_post_with_access(supabase, salon_id, post_id)

    existing = (
        supabase
        .table("salon_post_likes")
        .select("id")
        .eq("post_id", post_id)
        .eq("user_id", user["id"])
        .single()
        .execute()
    )

    liked = False
    if existing.data:
        supabase.table("salon_post_likes").delete().eq("id", existing.data["id"]).execute()
    else:
        supabase.table("salon_post_likes").insert({"post_id": post_id, "user_id": user["id"]}).execute()
        liked = True

    like_count_resp = (
        supabase
        .table("salon_post_likes")
        .select("id", count="exact")
        .eq("post_id", post_id)
        .execute()
    )
    like_count = getattr(like_count_resp, "count", 0) or 0

    return SalonPostLikeResponse(post_id=post_id, user_id=user["id"], liked=liked, like_count=like_count)
