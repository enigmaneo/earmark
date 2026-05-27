import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.auth import get_current_user
from earmark.database import get_session
from earmark.earmark_auth import decode_access_token
from earmark.models import KosyncUser, User
from earmark.schemas import KosyncUserCreate, KosyncUserCreated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

_optional_bearer = HTTPBearer(auto_error=False)


async def _get_optional_web_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(str(payload.get("sub", "")))
    except Exception:
        logger.debug("Invalid session token", exc_info=True)
        return None
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


@router.post("/create", response_model=KosyncUserCreated, status_code=201)
async def create_user(
    body: KosyncUserCreate,
    session: AsyncSession = Depends(get_session),
    web_user: User | None = Depends(_get_optional_web_user),
) -> KosyncUserCreated:
    existing = await session.execute(select(KosyncUser).where(KosyncUser.username == body.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=402, detail="Username already taken")

    user = KosyncUser(
        username=body.username,
        password_hash=body.password,
        user_id=web_user.id if web_user else None,
    )
    session.add(user)
    await session.commit()
    return KosyncUserCreated(username=body.username)


@router.get("/auth")
async def auth_user(user: KosyncUser = Depends(get_current_user)) -> dict[str, str]:
    return {"authorized": "OK"}
