from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CreatorFollowRequest(BaseModel):
    notify_email: Optional[bool] = None


class CreatorFollowStatusResponse(BaseModel):
    creator_id: str
    follower_id: Optional[str] = None
    following: bool
    notify_email: bool
    follower_count: int
    last_notified_at: Optional[datetime] = None
