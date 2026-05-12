from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.database import get_session
from earmark.models import User


async def get_current_user(
    x_auth_user: str = Header(alias="x-auth-user"),
    x_auth_key: str = Header(alias="x-auth-key"),
    session: AsyncSession = Depends(get_session),
) -> User:
    result = await session.execute(select(User).where(User.username == x_auth_user))
    user = result.scalar_one_or_none()
    if user is None or user.password_hash != x_auth_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user
