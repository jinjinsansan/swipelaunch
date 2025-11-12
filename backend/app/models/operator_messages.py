"""Pydantic schemas for operator broadcast messages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class OperatorMessageSegment(BaseModel):
    segment_type: str = Field(default="all_sellers", description="ターゲット種別 (例: all_sellers)")
    segment_payload: Dict[str, Any] = Field(default_factory=dict)


class OperatorMessageCreateRequest(BaseModel):
    title: str
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    category: str = "general"
    priority: str = "normal"
    send_at: Optional[datetime] = None
    send_now: bool = False
    target_segments: List[OperatorMessageSegment] = Field(default_factory=list)
    send_email: bool = False
    email_subject: Optional[str] = None
    email_from_name: Optional[str] = None
    email_from_address: Optional[str] = None
    email_reply_to: Optional[str] = None
    automated: Optional[bool] = None
    related_note_id: Optional[str] = None
    related_creator_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class OperatorMessageUpdateRequest(BaseModel):
    title: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    send_at: Optional[datetime] = None
    target_segments: Optional[List[OperatorMessageSegment]] = None
    send_email: Optional[bool] = None
    email_subject: Optional[str] = None
    email_from_name: Optional[str] = None
    email_from_address: Optional[str] = None
    email_reply_to: Optional[str] = None
    automated: Optional[bool] = None
    related_note_id: Optional[str] = None
    related_creator_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class OperatorMessageResponse(BaseModel):
    id: str
    title: str
    body_text: Optional[str]
    body_html: Optional[str]
    category: str
    priority: str
    status: str
    send_at: Optional[datetime]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    admin_hidden: bool = False
    admin_archived_at: Optional[datetime] = None
    segment_summary: List[OperatorMessageSegment] = Field(default_factory=list)
    send_email: bool = False
    email_subject: Optional[str] = None
    email_from_name: Optional[str] = None
    email_from_address: Optional[str] = None
    email_reply_to: Optional[str] = None
    automated: bool = False
    related_note_id: Optional[str] = None
    related_creator_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OperatorMessageListResponse(BaseModel):
    data: List[OperatorMessageResponse]
    total: int
    limit: int
    offset: int


class OperatorMessageRecipientResponse(BaseModel):
    id: str
    message_id: str
    user_id: str
    title: str
    body_text: Optional[str]
    body_html: Optional[str]
    category: str
    priority: str
    delivery_status: str
    read_at: Optional[datetime]
    archived: bool
    send_at: Optional[datetime]
    created_at: datetime


class OperatorMessageFeedResponse(BaseModel):
    data: List[OperatorMessageRecipientResponse]
    total: int
    limit: int
    offset: int


class OperatorMessageUnreadCountResponse(BaseModel):
    unread_count: int


class OperatorMessageReadRequest(BaseModel):
    read: bool = True
    archive: Optional[bool] = None


class OperatorMessageHideRequest(BaseModel):
    hidden: bool = True


class OperatorMessageArchiveRequest(BaseModel):
    archived: bool = True
