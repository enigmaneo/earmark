import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from earmark.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class Base(DeclarativeBase):
    pass


def sync_database_url(url: str) -> str:
    """Convert an async SQLAlchemy URL to its synchronous form for Alembic."""
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session  # type: ignore[misc]


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    sync_url = sync_database_url(settings.database_url)
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_INI.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sync_url)

    # Adopt a pre-Alembic database: if app tables already exist but Alembic has
    # never run here, stamp the baseline (which matches the legacy create_all
    # schema) so the remaining migrations apply on top instead of recreating it.
    sync_engine = create_engine(sync_url)
    try:
        with sync_engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "users" in tables:
            baseline = ScriptDirectory.from_config(cfg).get_bases()[0]
            logger.info("Pre-Alembic database detected; stamping baseline %s", baseline)
            command.stamp(cfg, baseline)
    finally:
        sync_engine.dispose()

    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Bring the database schema up to date by running Alembic migrations.

    Alembic runs synchronously and starts its own event loop internals, so it
    is dispatched to a worker thread to avoid clashing with the running loop.
    """
    await asyncio.to_thread(_run_migrations)
