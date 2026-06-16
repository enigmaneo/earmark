"""Centralised logging setup.

Console logging keeps the existing human-readable (or rich) output and is configured at import
time, before the database exists. File logging writes JSON lines to ``log_dir/earmark.log`` and is
configured once settings have been seeded; it can be re-applied at runtime when a ``log_*`` setting
changes. Rotation is handled by Python's stdlib handlers — there is no separate scheduler task.
"""

import logging
import logging.handlers
import time
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.app_settings import get_effective_int, get_effective_str
from earmark.config import settings

logger = logging.getLogger(__name__)

LOG_FILENAME = "earmark.log"

# Marks the handler we own so re-configuration is idempotent (we remove only ours).
_FILE_HANDLER_NAME = "earmark_file"


def configure_console_logging() -> None:
    """Configure root console logging from env settings (called at import + after Alembic)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    if settings.log_pretty:
        from rich.logging import RichHandler

        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True)],
            force=True,
        )
    else:
        logging.basicConfig(level=level, force=True)


def log_dir() -> Path:
    return Path(settings.log_dir)


def log_file_path() -> Path:
    return log_dir() / LOG_FILENAME


def _build_file_handler(
    strategy: str, max_size_mb: int, when: str, backup_count: int
) -> logging.Handler:
    path = str(log_file_path())
    if strategy == "time":
        handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
            path, when=when, backupCount=backup_count, encoding="utf-8"
        )
    else:
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )
    handler.set_name(_FILE_HANDLER_NAME)
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    # The literal Z above claims UTC, so render asctime in UTC (default is localtime).
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    return handler


async def configure_file_logging(session: AsyncSession) -> None:
    """Attach (or re-attach) the rotating JSON file handler using effective settings."""
    strategy = await get_effective_str(
        "log_rotation_strategy", settings.log_rotation_strategy, session
    )
    max_size_mb = await get_effective_int("log_max_size_mb", settings.log_max_size_mb, session)
    when = await get_effective_str("log_rotation_when", settings.log_rotation_when, session)
    backup_count = await get_effective_int("log_backup_count", settings.log_backup_count, session)

    log_dir().mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _FILE_HANDLER_NAME]:
        root.removeHandler(existing)
        existing.close()

    root.addHandler(_build_file_handler(strategy, max_size_mb, when, backup_count))
    logger.info(
        "File logging configured: strategy=%s backup_count=%s path=%s",
        strategy,
        backup_count,
        log_file_path(),
    )
