from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from earmark.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session  # type: ignore[misc]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Stopgap migration for additive columns (no alembic wired up yet).
        for stmt in (
            "ALTER TABLE alignment_jobs ADD COLUMN warnings TEXT",
            "ALTER TABLE alignment_jobs ADD COLUMN ebook_source VARCHAR(20)",
            "ALTER TABLE alignment_jobs ADD COLUMN ebook_source_ref VARCHAR(1000)",
            "ALTER TABLE abs_ebook_mappings ADD COLUMN ebook_source VARCHAR(20) NOT NULL DEFAULT 'local'",
            "ALTER TABLE abs_ebook_mappings ADD COLUMN ebook_source_ref VARCHAR(1000)",
        ):
            try:
                await conn.exec_driver_sql(stmt)
            except Exception:
                pass  # column already exists
