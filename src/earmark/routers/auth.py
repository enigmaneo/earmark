import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.database import get_session
from earmark.earmark_auth import (
    create_access_token,
    get_current_earmark_user,
    hash_password,
    kosync_hash,
    verify_password,
)
from earmark.models import KosyncUser, User
from earmark.ratelimit import limiter
from earmark.schemas import TokenResponse, UserCreate, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(
    request: Request, body: UserRegister, session: AsyncSession = Depends(get_session)
) -> User:
    # Validate everything before persisting so a conflict leaves no half-created account.
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    kosync_password_hash = kosync_hash(body.kosync_password)
    result = await session.execute(
        select(KosyncUser).where(KosyncUser.username == body.kosync_username)
    )
    kosync_user = result.scalar_one_or_none()
    if kosync_user is not None and (
        kosync_user.user_id is not None
        or not secrets.compare_digest(kosync_user.password_hash, kosync_password_hash)
    ):
        # Username taken by another account, or it exists unlinked but the password doesn't
        # match — either way we can't safely adopt it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="KOSync username already taken"
        )

    user = User(email=body.email, password_hash=hash_password(body.password))
    session.add(user)
    await session.flush()

    if kosync_user is not None:
        # Adopt the existing unlinked KosyncUser; its reading progress comes along via the FK.
        kosync_user.user_id = user.id
        session.add(kosync_user)
    else:
        session.add(
            KosyncUser(
                username=body.kosync_username,
                password_hash=kosync_password_hash,
                user_id=user.id,
            )
        )

    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request, body: UserCreate, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id), "email": user.email})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_earmark_user)) -> User:
    return user
