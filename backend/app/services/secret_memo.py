from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.config import get_supabase_client, settings
from app.services.platform_settings import SETTINGS_TABLE

SECRET_MEMO_KEY = "admin_secret_memo"
SECRET_MEMO_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@dataclass
class SecretMemoFile:
    id: str
    filename: str
    mime_type: str
    size: int
    data_base64: str
    uploaded_at: str


@dataclass
class SecretMemoRecord:
    content: str
    files: List[SecretMemoFile] = field(default_factory=list)
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deserialize_files(raw_files: object) -> List[SecretMemoFile]:
    files: List[SecretMemoFile] = []
    if not isinstance(raw_files, list):
        return files
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("id") or "")
        if not file_id:
            continue
        files.append(
            SecretMemoFile(
                id=file_id,
                filename=str(item.get("filename") or ""),
                mime_type=str(item.get("mime_type") or "application/octet-stream"),
                size=int(item.get("size") or 0),
                data_base64=str(item.get("data_base64") or ""),
                uploaded_at=str(item.get("uploaded_at") or _now_iso()),
            )
        )
    return files


def _serialize_files(files: List[SecretMemoFile]) -> List[dict]:
    return [
        {
            "id": file.id,
            "filename": file.filename,
            "mime_type": file.mime_type,
            "size": file.size,
            "data_base64": file.data_base64,
            "uploaded_at": file.uploaded_at,
        }
        for file in files
    ]


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
        return SecretMemoRecord(content="")

    row = rows[0]
    value = row.get("value")
    value_dict = value if isinstance(value, dict) else {}
    files = _deserialize_files(value_dict.get("files"))
    content = _extract_content(value)
    updated_at = _stringify(row.get("updated_at"))
    updated_by = _stringify(row.get("updated_by"))
    return SecretMemoRecord(content=content, files=files, updated_at=updated_at, updated_by=updated_by)


def _persist_secret_memo(record: SecretMemoRecord, actor_id: Optional[str], client: Optional[Client]) -> None:
    payload = {
        "key": SECRET_MEMO_KEY,
        "value": {
            "content": record.content,
            "files": _serialize_files(record.files),
        },
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


def save_secret_memo(content: str, actor_id: Optional[str], client: Optional[Client] = None) -> SecretMemoRecord:
    client = _ensure_table_client(client)
    record = get_secret_memo_record(client)
    record.content = content
    _persist_secret_memo(record, actor_id, client)
    return get_secret_memo_record(client=client)

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


def add_secret_memo_file(
    *,
    filename: str,
    mime_type: str,
    data_base64: str,
    actor_id: Optional[str],
    client: Optional[Client] = None,
) -> SecretMemoFile:
    client = _ensure_table_client(client)
    if not data_base64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ファイル内容が空です",
        )
    try:
        decoded = base64.b64decode(data_base64, validate=True)
    except Exception as exc:  # pragma: no cover - base64 errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ファイルのエンコード形式が不正です",
        ) from exc

    if len(decoded) > SECRET_MEMO_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ファイルサイズが制限を超えています (最大5MB)",
        )

    record = get_secret_memo_record(client)
    if len(record.files) >= 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="登録可能なファイル数の上限に達しました",
        )

    file = SecretMemoFile(
        id=str(uuid4()),
        filename=filename or "untitled",
        mime_type=mime_type or "application/octet-stream",
        size=len(decoded),
        data_base64=data_base64,
        uploaded_at=_now_iso(),
    )
    record.files.append(file)
    _persist_secret_memo(record, actor_id, client)
    return file


def get_secret_memo_file(file_id: str, client: Optional[Client] = None) -> SecretMemoFile:
    record = get_secret_memo_record(client)
    for file in record.files:
        if file.id == file_id:
            return file
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="指定されたファイルが見つかりません",
    )


def remove_secret_memo_file(
    file_id: str,
    actor_id: Optional[str],
    client: Optional[Client] = None,
) -> SecretMemoRecord:
    client = _ensure_table_client(client)
    record = get_secret_memo_record(client)
    index = next((idx for idx, file in enumerate(record.files) if file.id == file_id), None)
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたファイルが見つかりません",
        )
    record.files.pop(index)
    _persist_secret_memo(record, actor_id, client)
    return get_secret_memo_record(client=client)
