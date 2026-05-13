from datetime import datetime

from pydantic import BaseModel, EmailStr


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
    filename: str | None = None
    title: str | None = None
    authors: str | None = None
    is_latest: bool | None = None


class ProgressList(BaseModel):
    data: list[ProgressListItem]
    total: int
    page: int
    per_page: int
