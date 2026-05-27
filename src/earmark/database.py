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

        # Older DBs created abs_ebook_mappings.ebook_path / ebook_filename
        # with NOT NULL. Calibre-source mappings must leave those null, so
        # drop the constraint in-place via SQLite's writable_schema trick.
        if settings.database_url.startswith("sqlite"):
            await _relax_not_null_sqlite(
                conn,
                table="abs_ebook_mappings",
                columns=("ebook_path", "ebook_filename"),
            )


async def _relax_not_null_sqlite(conn, table: str, columns: tuple[str, ...]) -> None:
    """Remove NOT NULL from the named columns of `table` by editing sqlite_master."""
    info = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    rows = info.fetchall()
    needs_fix = any(name in columns and notnull == 1 for _, name, _, notnull, _, _ in rows)
    if not needs_fix:
        return

    create_row = await conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    row = create_row.fetchone()
    if row is None:
        return
    create_sql = row[0]
    new_sql = create_sql
    for col in columns:
        # Match "<col> <type...> NOT NULL" and drop the NOT NULL.
        import re as _re

        new_sql = _re.sub(
            rf"(\b{_re.escape(col)}\b\s+[A-Z]+(?:\(\d+\))?)\s+NOT NULL",
            r"\1",
            new_sql,
        )
    if new_sql == create_sql:
        return

    await conn.exec_driver_sql("PRAGMA writable_schema=ON")
    try:
        await conn.exec_driver_sql(
            "UPDATE sqlite_master SET sql = ? WHERE type='table' AND name = ?",
            (new_sql, table),
        )
    finally:
        await conn.exec_driver_sql("PRAGMA writable_schema=OFF")
