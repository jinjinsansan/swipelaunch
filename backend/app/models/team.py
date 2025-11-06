from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class TeamSummary(BaseModel):
    id: str
    name: Optional[str]
    owner_user_id: str
    role: str
    created_at: Optional[datetime] = None


class TeamMemberResponse(BaseModel):
    user_id: str
    email: Optional[str]
    username: Optional[str]
    role: str
    status: str
    invited_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class TeamMemberListResponse(BaseModel):
    team_id: str
    members: List[TeamMemberResponse]


class TeamInviteRequest(BaseModel):
    email: EmailStr


class TeamInviteResponse(BaseModel):
    invitation_id: str
    team_id: str
    email: EmailStr
    role: str
    status: str
    expires_at: datetime


class TeamUpdateMemberRequest(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(active|invited|disabled)$")
