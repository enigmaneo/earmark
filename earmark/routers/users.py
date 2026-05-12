import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.auth import get_current_user
from earmark.database import get_session
from earmark.models import User
from earmark.schemas import UserCreate, UserCreated

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/create", response_model=UserCreated, status_code=201)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> UserCreated:
    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=402, detail="Username already taken")

    password_hash = hashlib.md5(body.password.encode()).hexdigest()
    user = User(username=body.username, password_hash=password_hash)
    session.add(user)
    await session.commit()
    return UserCreated(username=body.username)


@router.get("/auth")
async def auth_user(user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"authorized": "OK"}
