"""Pydantic models for salon events."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SalonEventCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=4000)
    start_at: datetime
    end_at: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=500)
    meeting_url: Optional[str] = Field(None, max_length=500)
    is_public: bool = Field(default=True)
    capacity: Optional[int] = Field(None, ge=1)


class SalonEventUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=4000)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=500)
    meeting_url: Optional[str] = Field(None, max_length=500)
    is_public: Optional[bool] = None
    capacity: Optional[int] = Field(None, ge=1)


class SalonEventResponse(BaseModel):
    id: str
    salon_id: str
    organizer_id: str
    title: str
    description: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    location: Optional[str]
    meeting_url: Optional[str]
    is_public: bool
    capacity: Optional[int]
    attendee_count: int
    is_attending: bool
    created_at: datetime
    updated_at: datetime


class SalonEventListResponse(BaseModel):
    data: List[SalonEventResponse]
    total: int
    limit: int
    offset: int


class SalonEventAttendeeResponse(BaseModel):
    id: str
    event_id: str
    user_id: str
    status: str
    note: Optional[str]
    created_at: datetime
    updated_at: datetime
    username: Optional[str]


class SalonEventAttendeeListResponse(BaseModel):
    data: List[SalonEventAttendeeResponse]
    total: int
    limit: int
    offset: int


class SalonEventAttendRequest(BaseModel):
    status: Optional[str] = Field(default="GOING", max_length=32)
    note: Optional[str] = Field(None, max_length=500)
