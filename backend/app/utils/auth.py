from datetime import datetime, timedelta
from typing import Dict, Any

import jwt
from fastapi import HTTPException, status

from app.config import settings

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


def decode_access_token(token: str) -> Dict[str, Any]:
    """アクセストークンを検証してペイロードを返却"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
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
