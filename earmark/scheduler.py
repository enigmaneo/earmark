import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from earmark.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def sync_progress() -> None:
    logger.info("Running progress sync")
    # TODO: implement Audiobookshelf <-> KOSync sync


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
