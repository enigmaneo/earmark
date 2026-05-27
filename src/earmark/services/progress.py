from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.config import settings
from earmark.models import AbsEbookMapping, ReadingProgress


async def resolve_title_from_mapping(session: AsyncSession, document: str) -> str | None:
    result = await session.execute(
        select(AbsEbookMapping).where(AbsEbookMapping.kosync_document == document)
    )
    mapping = result.scalar_one_or_none()
    return mapping.abs_title if mapping is not None else None


async def backfill_progress_titles(
    session: AsyncSession, *, kosync_user_id: int, document: str, title: str
) -> None:
    await session.execute(
        update(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == kosync_user_id,
            ReadingProgress.document == document,
        )
        .values(title=title)
    )


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
    updated_at: datetime | None = None,
) -> ReadingProgress:
    existing_latest = (
        await session.execute(
            select(ReadingProgress).where(
                ReadingProgress.kosync_user_id == kosync_user_id,
                ReadingProgress.document == document,
                ReadingProgress.is_latest == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()

    if existing_latest is not None and existing_latest.progress == progress:
        return existing_latest

    result = await session.execute(
        select(AbsEbookMapping).where(AbsEbookMapping.kosync_document == document)
    )
    mapping = result.scalar_one_or_none()
    mapped_title = mapping.abs_title if mapping is not None else None
    resolved_title = mapped_title or title or document

    if mapping is not None:
        from earmark.models import KosyncUser
        kosync_user = await session.get(KosyncUser, kosync_user_id)
        if kosync_user is not None and kosync_user.user_id is None:
            kosync_user.user_id = mapping.user_id
            session.add(kosync_user)
            await session.flush()

    await session.execute(
        update(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == kosync_user_id,
            ReadingProgress.document == document,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
        .values(is_latest=False)
    )

    if mapped_title is not None:
        await session.execute(
            update(ReadingProgress)
            .where(
                ReadingProgress.kosync_user_id == kosync_user_id,
                ReadingProgress.document == document,
            )
            .values(title=resolved_title)
        )

    record = ReadingProgress(
        kosync_user_id=kosync_user_id,
        document=document,
        progress=progress,
        percentage=percentage,
        device=device,
        device_id=device_id,
        title=resolved_title,
        authors=authors,
        filename=filename,
        is_latest=True,
        updated_at=updated_at or datetime.now(ZoneInfo(settings.timezone)),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record
