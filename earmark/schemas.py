from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    id: int
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class KosyncUserCreate(BaseModel):
    username: str
    password: str


class KosyncUserCreated(BaseModel):
    username: str


class MetadataIn(BaseModel):
    filename: str | None = None
    title: str | None = None
    authors: str | None = None


class ProgressUpsert(BaseModel):
    document: str
    progress: str
    percentage: float
    device: str
    device_id: str
    metadata: MetadataIn | None = None


class ProgressResponse(BaseModel):
    document: str
    progress: str
    percentage: float
    device: str
    device_id: str
    timestamp: int

    model_config = {"from_attributes": True}


class ProgressListItem(ProgressResponse):
    id: int
    filename: str | None = None
    title: str | None = None
    authors: str | None = None
    is_latest: bool | None = None


class DocumentSummary(BaseModel):
    document: str
    title: str | None = None


class ProgressList(BaseModel):
    data: list[ProgressListItem]
    total: int
    page: int
    per_page: int


class AlignmentJobCreate(BaseModel):
    abs_item_id: str


class AlignmentJobRead(BaseModel):
    id: int
    abs_item_id: str
    status: str
    error_message: str | None
    paragraph_count: int | None
    fragment_count: int | None
    audio_offset_seconds: float | None
    sync_map_path: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SyncMapEntry(BaseModel):
    id: str
    audio_start: float
    audio_end: float
    ebook_pos: str
    text_snippet: str
