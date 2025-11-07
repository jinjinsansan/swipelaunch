from datetime import datetime, timedelta
from typing import Any, Dict

import jwt
from fastapi import HTTPException, status

from app.config import get_supabase_client, settings
from app.services.account_sharing import INVITE_STATUS_ACTIVE

ALGORITHM = "HS256"


def create_access_token(user_id: str) -> str:
    """指定したユーザーIDで署名済みアクセストークンを生成"""
    expires_delta = timedelta(minutes=settings.access_token_expires_minutes)
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_delegate_access_token(owner_user_id: str, delegate_user_id: str) -> str:
    expires_delta = timedelta(minutes=settings.access_token_expires_minutes)
    now = datetime.utcnow()
    payload = {
        "sub": owner_user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "delegate_id": delegate_user_id,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """アクセストークンを検証してペイロードを返却"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの有効期限が切れています"
        )
    except jwt.PyJWTError as exc:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なトークンです"
        ) from exc

    delegate_id = payload.get("delegate_id")
    if delegate_id:
        owner_user_id = payload.get("sub")
        if not owner_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効なトークンです")

        client = get_supabase_client()
        response = (
            client
            .table("account_shares")
            .select("status")
            .eq("owner_user_id", owner_user_id)
            .eq("delegate_user_id", delegate_id)
            .eq("status", INVITE_STATUS_ACTIVE)
            .maybe_single()
            .execute()
        )
        share = getattr(response, "data", None)
        if not share:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="共有アクセスが無効です")

    return payload
