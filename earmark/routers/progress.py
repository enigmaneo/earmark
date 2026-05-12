from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.auth import get_current_user
from earmark.database import get_session
from earmark.models import ReadingProgress, User
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    result = await session.execute(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user.id,
            ReadingProgress.document == body.document,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        record = ReadingProgress(
            user_id=user.id,
            document=body.document,
            progress=body.progress,
            percentage=body.percentage,
            device=body.device,
            device_id=body.device_id,
            filename=body.metadata.filename if body.metadata else None,
            title=body.metadata.title if body.metadata else None,
            authors=body.metadata.authors if body.metadata else None,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
    elif body.percentage > record.percentage:
        record.progress = body.progress
        record.percentage = body.percentage
        record.device = body.device
        record.device_id = body.device_id
        if body.metadata:
            if body.metadata.filename is not None:
                record.filename = body.metadata.filename
            if body.metadata.title is not None:
                record.title = body.metadata.title
            if body.metadata.authors is not None:
                record.authors = body.metadata.authors
        await session.commit()
        await session.refresh(record)

    return _to_response(record)


@router.get("/progress/{document}", response_model=ProgressResponse)
async def get_progress(
    document: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    result = await session.execute(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user.id,
            ReadingProgress.document == document,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_response(record)


@router.get("/progress", response_model=ProgressList)
async def list_progress(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
) -> ProgressList:
    count_result = await session.execute(
        select(func.count()).select_from(ReadingProgress).where(ReadingProgress.user_id == user.id)
    )
    total = count_result.scalar_one()

    rows_result = await session.execute(
        select(ReadingProgress)
        .where(ReadingProgress.user_id == user.id)
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    result = await session.execute(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user.id,
            ReadingProgress.document == document,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(record)
    await session.commit()
    return {"deleted": document}
