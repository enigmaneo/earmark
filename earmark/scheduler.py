import asyncio
import bisect
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from earmark.config import settings
from earmark.database import AsyncSessionLocal
from earmark.models import AbsEbookMapping, AlignmentJob, KosyncUser, ReadingProgress, User
from earmark.services.audiobookshelf import AudiobookshelfClient
from earmark.services.progress import write_reading_progress

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_SYNC_DEVICE = "earmark-sync"


def _load_sync_map(path: str) -> list[dict[str, Any]] | None:
    p = Path(path)
    if not p.exists():
        logger.error("Sync map not found: %s", path)
        return None
    try:
        entries: list[dict[str, Any]] = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load sync map %s: %s", path, exc)
        return None
    if not entries:
        logger.warning("Sync map is empty: %s", path)
        return None
    return entries


def _audio_to_kosync(
    current_time: float, duration: float, sync_map: list[dict[str, Any]]
) -> tuple[str, float]:
    starts = [e["audio_start"] for e in sync_map]
    idx = bisect.bisect_right(starts, current_time) - 1
    idx = max(0, min(idx, len(sync_map) - 1))
    entry = sync_map[idx]
    percentage = current_time / duration if duration > 0 else 0.0
    return entry["ebook_pos"], percentage


_DOCFRAG_RE = re.compile(r"/body/DocFragment\[(\d+)\]")
_ELEM_RE = re.compile(r"/body/\w+\[(\d+)\]")


def _kosync_to_audio(
    xpath: str, sync_map: list[dict[str, Any]]
) -> float | None:
    frag_match = _DOCFRAG_RE.search(xpath)
    if not frag_match:
        return None
    n = int(frag_match.group(1))

    elem_match = _ELEM_RE.search(xpath)
    m = int(elem_match.group(1)) if elem_match else 1

    candidates = [e for e in sync_map if f"DocFragment[{n}]" in e["ebook_pos"]]
    if not candidates:
        return None

    def _elem_index(entry: dict[str, Any]) -> int:
        em = _ELEM_RE.search(entry["ebook_pos"])
        return int(em.group(1)) if em else 1

    best = min(candidates, key=lambda e: abs(_elem_index(e) - m))
    return float(best["audio_start"])


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def _write_abs_to_kosync(
    mapping: AbsEbookMapping,
    abs_data: dict[str, Any],
    sync_map: list[dict[str, Any]],
    session: AsyncSession,
    *,
    min_percentage: float | None = None,
) -> None:
    assert mapping.kosync_document  # caller guards this
    ebook_pos, new_pct = _audio_to_kosync(
        abs_data["currentTime"], abs_data["duration"], sync_map
    )
    if min_percentage is not None and new_pct <= min_percentage:
        logger.warning(
            "Skipping KOSync update for %s: new %.4f%% <= current %.4f%%",
            mapping.abs_item_id, new_pct, min_percentage,
        )
        return
    for ku in mapping.user.kosync_users:
        await write_reading_progress(
            session,
            kosync_user_id=ku.id,
            document=mapping.kosync_document,
            progress=ebook_pos,
            percentage=new_pct,
            device=_SYNC_DEVICE,
            device_id=_SYNC_DEVICE,
        )
    mapping.last_synced_at = datetime.now(UTC)
    await session.commit()
    logger.info("ABS→KOSync %s: %.4f%%", mapping.abs_item_id, new_pct)


async def _write_kosync_to_abs(
    mapping: AbsEbookMapping,
    ko_progress: ReadingProgress,
    abs_data: dict[str, Any] | None,
    abs_client: AudiobookshelfClient,
    sync_map: list[dict[str, Any]],
    session: AsyncSession,
) -> None:
    assert mapping.kosync_document  # caller guards this
    audio_time = _kosync_to_audio(ko_progress.progress, sync_map)
    if audio_time is None:
        frag = _DOCFRAG_RE.search(ko_progress.progress)
        logger.warning(
            "Cannot map KOSync XPath to ABS for %s: DocFragment[%s] not in sync map",
            mapping.abs_item_id, frag.group(1) if frag else "?",
        )
        return
    if abs_data is not None and audio_time <= abs_data["currentTime"]:
        duration = abs_data["duration"]
        logger.warning(
            "Skipping ABS update for %s: new %.4f%% <= current %.4f%%",
            mapping.abs_item_id,
            audio_time / duration * 100 if duration else 0.0,
            abs_data["currentTime"] / duration * 100 if duration else 0.0,
        )
        return
    await abs_client.update_progress(
        mapping.abs_item_id,
        current_time=audio_time,
        duration=abs_data["duration"] if abs_data else 0.0,
        progress=ko_progress.percentage,
    )
    mapping.last_synced_at = datetime.now(UTC)
    await session.commit()
    logger.info("KOSync→ABS %s: %.4f%%", mapping.abs_item_id, ko_progress.percentage)


async def _sync_mapping(
    mapping: AbsEbookMapping,
    abs_client: AudiobookshelfClient,
    session: AsyncSession,
) -> None:
    abs_item_id = mapping.abs_item_id

    if not mapping.kosync_document:
        logger.warning("Skipping %s: no kosync_document", abs_item_id)
        return

    if not mapping.user or not mapping.user.kosync_users:
        logger.warning("Skipping user %s: no KosyncUsers linked", mapping.user_id)
        return

    job = mapping.alignment_job
    if not job or job.status != "complete" or not job.sync_map_path:
        logger.warning("Skipping %s: no completed alignment job", abs_item_id)
        return

    sync_map = await asyncio.to_thread(_load_sync_map, job.sync_map_path)
    if sync_map is None:
        return

    try:
        abs_data = await abs_client.get_progress(abs_item_id)
    except Exception as exc:
        logger.error("Error fetching ABS progress for %s: %s", abs_item_id, exc)
        return

    ko_result = await session.execute(
        select(ReadingProgress)
        .join(KosyncUser, ReadingProgress.kosync_user_id == KosyncUser.id)
        .where(
            KosyncUser.user_id == mapping.user_id,
            ReadingProgress.document == mapping.kosync_document,
            ReadingProgress.is_latest == True,  # noqa: E712
        )
        .order_by(ReadingProgress.updated_at.desc())
        .limit(1)
    )
    ko_progress = ko_result.scalar_one_or_none()

    if abs_data is None and ko_progress is None:
        return

    # Skip if neither side has changed since last sync
    if abs_data is not None and ko_progress is not None and mapping.last_synced_at is not None:
        abs_ts = datetime.fromtimestamp(abs_data["lastUpdate"] / 1000, tz=UTC)
        ko_ts = _ensure_utc(ko_progress.updated_at)
        last = _ensure_utc(mapping.last_synced_at)
        if abs_ts <= last and ko_ts <= last:
            logger.debug("Skipping %s: no changes since last sync (%s)", abs_item_id, last)
            return

    if ko_progress is None:
        assert abs_data is not None
        await _write_abs_to_kosync(mapping, abs_data, sync_map, session)
    elif abs_data is None:
        await _write_kosync_to_abs(mapping, ko_progress, None, abs_client, sync_map, session)
    else:
        abs_ts = datetime.fromtimestamp(abs_data["lastUpdate"] / 1000, tz=UTC)
        ko_ts = _ensure_utc(ko_progress.updated_at)
        if abs_ts == ko_ts:
            return
        if abs_ts > ko_ts:
            await _write_abs_to_kosync(mapping, abs_data, sync_map, session,
                                       min_percentage=ko_progress.percentage)
        else:
            await _write_kosync_to_abs(
                mapping, ko_progress, abs_data, abs_client, sync_map, session
            )


async def sync_progress() -> None:
    logger.info("Running progress sync")
    started_at = asyncio.get_event_loop().time()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AbsEbookMapping)
            .join(AlignmentJob, AbsEbookMapping.alignment_job_id == AlignmentJob.id)
            .options(selectinload(AbsEbookMapping.user).selectinload(User.kosync_users))
            .where(
                AbsEbookMapping.kosync_document.isnot(None),
                AlignmentJob.status == "complete",
                AlignmentJob.sync_map_path.isnot(None),
            )
        )
        abs_client = AudiobookshelfClient()
        try:
            for mapping in result.scalars():
                try:
                    await _sync_mapping(mapping, abs_client, session)
                except Exception:
                    logger.exception("Error syncing mapping %s", mapping.id)
        finally:
            await abs_client.close()
    elapsed = asyncio.get_event_loop().time() - started_at
    logger.info("Progress sync complete (%.2fs)", elapsed)


def start_scheduler() -> None:
    scheduler.add_job(
        sync_progress,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="sync_progress",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    scheduler.shutdown()
