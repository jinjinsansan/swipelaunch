"""Pydantic models for salon roles and permissions."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


PERMISSION_FIELDS = (
    "manage_feed",
    "manage_events",
    "manage_assets",
    "manage_announcements",
    "manage_members",
    "manage_roles",
)


class SalonRoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="ロール名")
    description: Optional[str] = Field(None, description="説明")
    is_default: bool = Field(default=False, description="新規メンバーに自動付与するロールか")
    manage_feed: bool = Field(default=False, description="フィード投稿の管理権限")
    manage_events: bool = Field(default=False, description="イベントの管理権限")
    manage_assets: bool = Field(default=False, description="アセットライブラリの管理権限")
    manage_announcements: bool = Field(default=False, description="お知らせ管理権限")
    manage_members: bool = Field(default=False, description="メンバー管理権限")
    manage_roles: bool = Field(default=False, description="ロール設定の管理権限")


class SalonRoleCreateRequest(SalonRoleBase):
    pass


class SalonRoleUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_default: Optional[bool] = None
    manage_feed: Optional[bool] = None
    manage_events: Optional[bool] = None
    manage_assets: Optional[bool] = None
    manage_announcements: Optional[bool] = None
    manage_members: Optional[bool] = None
    manage_roles: Optional[bool] = None


class SalonRoleResponse(SalonRoleBase):
    id: str
    salon_id: str
    assigned_member_count: int = Field(default=0, description="このロールを持つメンバー数")
    created_at: str
    updated_at: str


class SalonRoleListResponse(BaseModel):
    data: list[SalonRoleResponse]
    total: int


class SalonRoleAssignRequest(BaseModel):
    user_id: str = Field(..., description="ロールを付与するユーザーID")


class SalonRolePermissions(BaseModel):
    manage_feed: bool = False
    manage_events: bool = False
    manage_assets: bool = False
    manage_announcements: bool = False
    manage_members: bool = False
    manage_roles: bool = False


class SalonRoleAssignmentResponse(BaseModel):
    role_id: str
    user_id: str
    salon_id: str
    assigned_by: Optional[str] = None
    created_at: str
