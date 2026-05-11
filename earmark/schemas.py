from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    id: int
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProgressUpdate(BaseModel):
    document: str
    progress: float
    device: str = ""
    device_id: str = ""


class ProgressRead(BaseModel):
    document: str
    progress: float
    updated_at: datetime

    model_config = {"from_attributes": True}
