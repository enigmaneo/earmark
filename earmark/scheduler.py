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
    if idx < 0:
        idx = 0
    # Clamp to last entry if currentTime is past the end
    if idx >= len(sync_map):
        idx = len(sync_map) - 1
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

    # Fetch ABS progress
    try:
        abs_data = await abs_client.get_progress(abs_item_id)
    except Exception as exc:
        logger.error("Error fetching ABS progress for %s: %s", abs_item_id, exc)
        return

    # Fetch latest KOSync progress across all KosyncUsers owned by this earmark User
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

    # Skip if neither side has changed since the last sync
    if abs_data is not None and ko_progress is not None and mapping.last_synced_at is not None:
        abs_ts_check = datetime.fromtimestamp(abs_data["lastUpdate"] / 1000, tz=UTC)
        raw_ko = ko_progress.updated_at
        ko_ts_check = raw_ko if raw_ko.tzinfo is not None else raw_ko.replace(tzinfo=UTC)
        last = mapping.last_synced_at if mapping.last_synced_at.tzinfo is not None \
            else mapping.last_synced_at.replace(tzinfo=UTC)
        if abs_ts_check <= last and ko_ts_check <= last:
            logger.debug("Skipping %s: no changes since last sync (%s)", abs_item_id, last)
            return

    # Determine direction
    if abs_data is None and ko_progress is None:
        return

    if abs_data is not None and ko_progress is None:
        # Write ABS position to KOSync unconditionally
        ebook_pos, percentage = _audio_to_kosync(
            abs_data["currentTime"], abs_data["duration"], sync_map
        )
        for ku in mapping.user.kosync_users:
            await write_reading_progress(
                session,
                kosync_user_id=ku.id,
                document=mapping.kosync_document,
                progress=ebook_pos,
                percentage=percentage,
                device=_SYNC_DEVICE,
                device_id=_SYNC_DEVICE,
            )
        mapping.last_synced_at = datetime.now(UTC)
        await session.commit()
        logger.info("ABS→KOSync %s: %s → %.4f%%", abs_item_id, None, percentage)
        return

    if ko_progress is not None and abs_data is None:
        # Write KOSync position to ABS unconditionally
        audio_time = _kosync_to_audio(ko_progress.progress, sync_map)
        if audio_time is None:
            frag_match = _DOCFRAG_RE.search(ko_progress.progress)
            n = frag_match.group(1) if frag_match else "?"
            logger.warning(
                "Cannot map KOSync XPath to ABS for %s: DocFragment[%s] not in sync map",
                abs_item_id, n,
            )
            return
        await abs_client.update_progress(
            abs_item_id,
            current_time=audio_time,
            duration=0.0,
            progress=ko_progress.percentage,
        )
        mapping.last_synced_at = datetime.now(UTC)
        await session.commit()
        logger.info("KOSync→ABS %s: %s → %.4f%%", abs_item_id, None, ko_progress.percentage)
        return

    # Both sides have progress — compare timestamps
    assert abs_data is not None and ko_progress is not None
    abs_ts = datetime.fromtimestamp(abs_data["lastUpdate"] / 1000, tz=UTC)
    raw_ts = ko_progress.updated_at
    ko_ts = raw_ts if raw_ts.tzinfo is not None else raw_ts.replace(tzinfo=UTC)

    if abs_ts == ko_ts:
        return

    if abs_ts > ko_ts:
        # ABS is newer → update KOSync
        ebook_pos, new_percentage = _audio_to_kosync(
            abs_data["currentTime"], abs_data["duration"], sync_map
        )
        if new_percentage <= ko_progress.percentage:
            logger.warning(
                "Skipping KOSync update for %s: new percentage %.4f <= current %.4f",
                abs_item_id, new_percentage, ko_progress.percentage,
            )
            return
        for ku in mapping.user.kosync_users:
            await write_reading_progress(
                session,
                kosync_user_id=ku.id,
                document=mapping.kosync_document,
                progress=ebook_pos,
                percentage=new_percentage,
                device=_SYNC_DEVICE,
                device_id=_SYNC_DEVICE,
            )
        mapping.last_synced_at = datetime.now(UTC)
        await session.commit()
        logger.info("ABS→KOSync %s: %.4f%% → %.4f%%", abs_item_id, ko_progress.percentage, new_percentage)
    else:
        # KOSync is newer → update ABS
        audio_time = _kosync_to_audio(ko_progress.progress, sync_map)
        if audio_time is None:
            frag_match = _DOCFRAG_RE.search(ko_progress.progress)
            n = frag_match.group(1) if frag_match else "?"
            logger.warning(
                "Cannot map KOSync XPath to ABS for %s: DocFragment[%s] not in sync map",
                abs_item_id, n,
            )
            return
        if audio_time <= abs_data["currentTime"]:
            duration = abs_data["duration"]
            logger.warning(
                "Skipping ABS update for %s: new position %.4f%% <= current %.4f%%",
                abs_item_id,
                audio_time / duration * 100 if duration else 0.0,
                abs_data["currentTime"] / duration * 100 if duration else 0.0,
            )
            return
        await abs_client.update_progress(
            abs_item_id,
            current_time=audio_time,
            duration=abs_data["duration"],
            progress=ko_progress.percentage,
        )
        mapping.last_synced_at = datetime.now(UTC)
        await session.commit()
        logger.info("KOSync→ABS %s: %.4f%% → %.4f%%", abs_item_id, abs_data["progress"], ko_progress.percentage)


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
