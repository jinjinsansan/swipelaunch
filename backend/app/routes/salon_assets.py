"""Salon asset library endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_supabase_client
from app.models.salon_assets import (
    SalonAssetListResponse,
    SalonAssetMetadata,
    SalonAssetResponse,
)
from app.routes.salon_events import _get_salon_and_access  # reuse permission helper
from app.utils.auth import decode_access_token
from app.utils.salon_permissions import ensure_permission, get_user_permissions
from app.services.storage import storage


router = APIRouter(prefix="/salons/{salon_id}/assets", tags=["salon-assets"])
security = HTTPBearer()

VISIBILITY_VALUES = {"MEMBERS", "PUBLIC"}


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


def _map_asset_record(record: Dict[str, Any]) -> SalonAssetResponse:
    return SalonAssetResponse(
        id=record.get("id"),
        salon_id=record.get("salon_id"),
        uploader_id=record.get("uploader_id"),
        asset_type=record.get("asset_type", "UNKNOWN"),
        title=record.get("title"),
        description=record.get("description"),
        file_url=record.get("file_url"),
        thumbnail_url=record.get("thumbnail_url"),
        content_type=record.get("content_type", ""),
        file_size=int(record.get("file_size", 0)),
        visibility=record.get("visibility", "MEMBERS"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


def _parse_visibility(value: Optional[str]) -> str:
    if not value:
        return "MEMBERS"
    upper_value = value.upper()
    if upper_value not in VISIBILITY_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="公開設定が不正です")
    return upper_value


def _detect_asset_type(content_type: str, preferred: Optional[str]) -> str:
    if preferred:
        return preferred.upper()
    if content_type.startswith("image/"):
        return "IMAGE"
    if content_type.startswith("video/"):
        return "VIDEO"
    if content_type in {"application/pdf", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
        return "DOCUMENT"
    return "FILE"


@router.get("", response_model=SalonAssetListResponse)
async def list_assets(
    salon_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    visibility: Optional[str] = Query(None, description="フィルタする公開設定"),
    asset_type: Optional[str] = Query(None, description="フィルタするアセット種別"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _get_salon_and_access(supabase, salon_id, user["id"])

    filters = {"salon_id": salon_id}
    if visibility:
        filters["visibility"] = _parse_visibility(visibility)
    if asset_type:
        filters["asset_type"] = asset_type.upper()

    count_query = supabase.table("salon_assets").select("id", count="exact")
    data_query = supabase.table("salon_assets").select("*")
    for key, value in filters.items():
        count_query = count_query.eq(key, value)
        data_query = data_query.eq(key, value)

    count_resp = count_query.execute()
    total = getattr(count_resp, "count", 0) or 0

    range_end = offset + limit - 1
    data_resp = (
        data_query
        .order("created_at", asc=False)
        .range(offset, range_end)
        .execute()
    )
    records = data_resp.data or []

    data = [_map_asset_record(record) for record in records]
    return SalonAssetListResponse(data=data, total=total, limit=limit, offset=offset)


@router.post("", response_model=SalonAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    salon_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    asset_type: Optional[str] = Form(None),
    visibility: Optional[str] = Form(None),
    thumbnail: Optional[UploadFile] = File(None),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_assets", "アセットを管理する権限がありません")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ファイルが選択されていません")
    content_type = file.content_type or "application/octet-stream"
    resolved_visibility = _parse_visibility(visibility)
    resolved_type = _detect_asset_type(content_type, asset_type)

    folder = f"salons/{salon_id}/assets"
    file_url = storage.upload_file(
        file_content=file_bytes,
        file_name=file.filename or "upload",
        content_type=content_type,
        folder=folder,
    )

    thumbnail_url: Optional[str] = None
    if thumbnail:
        thumb_bytes = await thumbnail.read()
        if thumb_bytes:
            thumb_type = thumbnail.content_type or "image/png"
            thumbnail_url = storage.upload_file(
                file_content=thumb_bytes,
                file_name=thumbnail.filename or "thumbnail",
                content_type=thumb_type,
                folder=f"salons/{salon_id}/assets/thumbnails",
            )

    asset_data: Dict[str, Any] = {
        "salon_id": salon_id,
        "uploader_id": user["id"],
        "asset_type": resolved_type,
        "title": title or None,
        "description": description or None,
        "file_url": file_url,
        "thumbnail_url": thumbnail_url,
        "content_type": content_type,
        "file_size": len(file_bytes),
        "visibility": resolved_visibility,
    }

    response = supabase.table("salon_assets").insert(asset_data).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="アセットの登録に失敗しました")

    record = response.data[0]
    return _map_asset_record(record)


@router.patch("/{asset_id}", response_model=SalonAssetResponse)
async def update_asset_metadata(
    salon_id: str,
    asset_id: str,
    payload: SalonAssetMetadata,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)
    ensure_permission(permissions, "manage_assets", "アセットを更新する権限がありません")

    existing_resp = (
        supabase
        .table("salon_assets")
        .select("*")
        .eq("id", asset_id)
        .eq("salon_id", salon_id)
        .single()
        .execute()
    )
    if not existing_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="アセットが見つかりません")

    updates: Dict[str, Any] = {}
    if payload.title is not None:
        updates["title"] = payload.title or None
    if payload.description is not None:
        updates["description"] = payload.description or None
    if payload.asset_type is not None:
        updates["asset_type"] = payload.asset_type.upper()
    if payload.visibility is not None:
        updates["visibility"] = _parse_visibility(payload.visibility)

    if not updates:
        return _map_asset_record(existing_resp.data)

    update_resp = (
        supabase
        .table("salon_assets")
        .update(updates)
        .eq("id", asset_id)
        .eq("salon_id", salon_id)
        .execute()
    )
    if not update_resp.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="アセットの更新に失敗しました")

    record = update_resp.data[0]
    return _map_asset_record(record)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    salon_id: str,
    asset_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user = _get_current_user(credentials)
    supabase = get_supabase_client()
    _, is_owner = _get_salon_and_access(supabase, salon_id, user["id"])
    permissions = get_user_permissions(supabase, salon_id, user["id"], is_owner=is_owner)

    asset_resp = (
        supabase
        .table("salon_assets")
        .select("*")
        .eq("id", asset_id)
        .eq("salon_id", salon_id)
        .single()
        .execute()
    )
    record = asset_resp.data
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="アセットが見つかりません")

    if not (is_owner or permissions.manage_assets or record.get("uploader_id") == user["id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="アセットを削除する権限がありません")

    file_url = record.get("file_url")
    thumbnail_url = record.get("thumbnail_url")

    supabase.table("salon_assets").delete().eq("id", asset_id).eq("salon_id", salon_id).execute()

    if file_url:
        storage.delete_file(file_url)
    if thumbnail_url:
        storage.delete_file(thumbnail_url)

    return None
