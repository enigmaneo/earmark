from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.database import get_session
from earmark.schemas import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/create", response_model=UserRead)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    # TODO: implement
    raise NotImplementedError
