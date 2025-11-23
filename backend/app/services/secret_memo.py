from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.config import get_supabase_client, settings
from app.services.platform_settings import SETTINGS_TABLE

SECRET_MEMO_KEY = "admin_secret_memo"


@dataclass
class SecretMemoRecord:
    content: str
    updated_at: Optional[str]
    updated_by: Optional[str]


def _extract_content(value: object) -> str:
    if isinstance(value, dict):
        raw = value.get("content")
        return str(raw or "")
    if value is None:
        return ""
    return str(value)


def _stringify(value: object) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _ensure_table_client(client: Optional[Client]) -> Client:
    return client or get_supabase_client()


def get_secret_memo_record(client: Optional[Client] = None) -> SecretMemoRecord:
    client = _ensure_table_client(client)
    try:
        response = (
            client
            .table(SETTINGS_TABLE)
            .select("value, updated_at, updated_by")
            .eq("key", SECRET_MEMO_KEY)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        message = getattr(exc, "message", "") or str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"極秘メモの取得に失敗しました: {message}",
        ) from exc

    rows = response.data or []
    if not rows:
        return SecretMemoRecord(content="", updated_at=None, updated_by=None)

    row = rows[0]
    content = _extract_content(row.get("value"))
    updated_at = _stringify(row.get("updated_at"))
    updated_by = _stringify(row.get("updated_by"))
    return SecretMemoRecord(content=content, updated_at=updated_at, updated_by=updated_by)


def save_secret_memo(content: str, actor_id: Optional[str], client: Optional[Client] = None) -> SecretMemoRecord:
    client = _ensure_table_client(client)
    payload = {
        "key": SECRET_MEMO_KEY,
        "value": {"content": content},
        "updated_by": actor_id,
    }
    try:
        (
            client
            .table(SETTINGS_TABLE)
            .upsert(payload)
            .execute()
        )
    except APIError as exc:
        message = getattr(exc, "message", "") or str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"極秘メモの保存に失敗しました: {message}",
        ) from exc

    return get_secret_memo_record(client=client)


def verify_secret_memo_password(password: str) -> None:
    expected = settings.secret_memo_password
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="極秘メモ用のパスワードが未設定です",
        )
    if not password or not hmac.compare_digest(password, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="極秘メモのパスワードが一致しません",
        )
