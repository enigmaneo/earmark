from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.auth import get_current_user
from earmark.database import get_session
from earmark.models import KosyncUser, ReadingProgress
from earmark.schemas import ProgressList, ProgressListItem, ProgressResponse, ProgressUpsert

router = APIRouter(prefix="/syncs", tags=["syncs"])


def _to_response(r: ReadingProgress) -> ProgressResponse:
    return ProgressResponse(
        document=r.document,
        progress=r.progress,
        percentage=r.percentage,
        device=r.device,
        device_id=r.device_id,
        timestamp=int(r.updated_at.timestamp()),
    )


def _to_list_item(r: ReadingProgress) -> ProgressListItem:
    return ProgressListItem(
        document=r.document,
        progress=r.progress,
        percentage=r.percentage,
        device=r.device,
        device_id=r.device_id,
        timestamp=int(r.updated_at.timestamp()),
        filename=r.filename,
        title=r.title,
        authors=r.authors,
    )


@router.put("/progress", response_model=ProgressResponse)
async def upsert_progress(
    body: ProgressUpsert,
    user: KosyncUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    await session.execute(
        update(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == user.id,
            ReadingProgress.document == body.document,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
        .values(is_latest=False)
    )
    record = ReadingProgress(
        kosync_user_id=user.id,
        document=body.document,
        progress=body.progress,
        percentage=body.percentage,
        device=body.device,
        device_id=body.device_id,
        filename=body.metadata.filename if body.metadata else None,
        title=body.metadata.title if body.metadata else None,
        authors=body.metadata.authors if body.metadata else None,
        is_latest=True,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return _to_response(record)


@router.get("/progress/{document}", response_model=ProgressResponse)
async def get_progress(
    document: str,
    user: KosyncUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    result = await session.execute(
        select(ReadingProgress).where(
            ReadingProgress.kosync_user_id == user.id,
            ReadingProgress.document == document,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_response(record)


@router.get("/progress", response_model=ProgressList)
async def list_progress(
    user: KosyncUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
) -> ProgressList:
    count_result = await session.execute(
        select(func.count())
        .select_from(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == user.id,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
    )
    total = count_result.scalar_one()

    rows_result = await session.execute(
        select(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == user.id,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    records = rows_result.scalars().all()

    return ProgressList(
        data=[_to_list_item(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.delete("/progress/{document}")
async def delete_progress(
    document: str,
    user: KosyncUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    exists = await session.execute(
        select(func.count())
        .select_from(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == user.id,
            ReadingProgress.document == document,
        )
    )
    if exists.scalar_one() == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await session.execute(
        delete(ReadingProgress).where(
            ReadingProgress.kosync_user_id == user.id,
            ReadingProgress.document == document,
        )
    )
    await session.commit()
    return {"deleted": document}
