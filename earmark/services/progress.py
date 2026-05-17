from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.models import ReadingProgress


async def write_reading_progress(
    session: AsyncSession,
    *,
    kosync_user_id: int,
    document: str,
    progress: str,
    percentage: float,
    device: str,
    device_id: str,
    title: str | None = None,
    authors: str | None = None,
    filename: str | None = None,
) -> ReadingProgress:
    await session.execute(
        update(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == kosync_user_id,
            ReadingProgress.document == document,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
        .values(is_latest=False)
    )
    record = ReadingProgress(
        kosync_user_id=kosync_user_id,
        document=document,
        progress=progress,
        percentage=percentage,
        device=device,
        device_id=device_id,
        title=title,
        authors=authors,
        filename=filename,
        is_latest=True,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record
