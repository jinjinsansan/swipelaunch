from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class AccountShareInviteRequest(BaseModel):
    email: EmailStr


class AccountShareOwnerShare(BaseModel):
    share_id: str
    delegate_user_id: str
    delegate_email: Optional[str]
    delegate_username: Optional[str]
    status: str
    invited_at: datetime
    accepted_at: Optional[datetime] = None
    expires_at: datetime


class AccountShareOwnerListResponse(BaseModel):
    shares: List[AccountShareOwnerShare]


class AccountShareDelegateShare(BaseModel):
    share_id: str
    owner_user_id: str
    owner_email: Optional[str]
    owner_username: Optional[str]
    status: str
    invited_at: datetime
    accepted_at: Optional[datetime] = None
    expires_at: datetime


class AccountShareDelegateListResponse(BaseModel):
    shares: List[AccountShareDelegateShare]


class AccountShareInviteResponse(BaseModel):
    share_id: str
    status: str
    expires_at: datetime
    invite_url: str


class AccountShareAcceptResponse(BaseModel):
    share_id: str
    owner_user_id: str
    delegate_user_id: str
    status: str
    accepted_at: datetime


class AccountAccessibleOwner(BaseModel):
    owner_user_id: str
    owner_email: Optional[str]
    owner_username: Optional[str]
    is_self: bool = False


class AccountAccessibleOwnersResponse(BaseModel):
    owners: List[AccountAccessibleOwner]


class AccountShareSessionRequest(BaseModel):
    owner_user_id: str


class AccountShareSessionResponse(BaseModel):
    owner_user_id: str
    delegate_user_id: Optional[str] = None
    access_token: str
    expires_in: int
