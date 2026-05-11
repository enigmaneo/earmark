from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.database import get_session
from earmark.schemas import ProgressRead, ProgressUpdate

router = APIRouter(prefix="/progress", tags=["progress"])


@router.put("/{username}/{document}", response_model=ProgressRead)
async def update_progress(
    username: str,
    document: str,
    body: ProgressUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProgressRead:
    # TODO: implement
    raise NotImplementedError


@router.get("/{username}/{document}", response_model=ProgressRead)
async def get_progress(
    username: str,
    document: str,
    session: AsyncSession = Depends(get_session),
) -> ProgressRead:
    # TODO: implement
    raise NotImplementedError
