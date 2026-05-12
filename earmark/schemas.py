from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str


class UserCreated(BaseModel):
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


class ProgressList(BaseModel):
    data: list[ProgressListItem]
    total: int
    page: int
    per_page: int
