import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from earmark.config import settings

logger = logging.getLogger(__name__)

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
    """Remove NOT NULL from the named columns of `table` by editing sqlite_master.

    Allows untyped/quoted column names and arbitrary modifiers (DEFAULT, COLLATE, …)
    between the column definition and the NOT NULL clause. After mutation we bump
    schema_version so the connection's cached schema reparses, then run
    integrity_check to catch any corruption from a malformed rewrite.
    """
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
    unmatched: list[str] = []
    for col in columns:
        # Match the column definition (optionally quoted name + everything up to
        # NOT NULL that isn't a comma or paren) and drop the NOT NULL clause.
        pattern = re.compile(
            rf'(["`\[]?{re.escape(col)}["`\]]?\s+[^,()]*?)\s+NOT\s+NULL',
            re.IGNORECASE,
        )
        new_sql, n = pattern.subn(r"\1", new_sql, count=1)
        if n == 0:
            unmatched.append(col)

    if unmatched:
        logger.warning(
            "Could not relax NOT NULL on %s.%s — regex did not match in CREATE TABLE statement. "
            "Calibre-source mappings may fail to insert until the schema is updated manually.",
            table,
            ", ".join(unmatched),
        )

    if new_sql == create_sql:
        return

    await conn.exec_driver_sql("PRAGMA writable_schema=ON")
    try:
        await conn.exec_driver_sql(
            "UPDATE sqlite_master SET sql = ? WHERE type='table' AND name = ?",
            (new_sql, table),
        )
        # Force the connection to reparse the schema on next access.
        version_row = await conn.exec_driver_sql("PRAGMA schema_version")
        current_version = version_row.fetchone()[0]
        await conn.exec_driver_sql(f"PRAGMA schema_version = {current_version + 1}")
    finally:
        await conn.exec_driver_sql("PRAGMA writable_schema=OFF")

    check = await conn.exec_driver_sql("PRAGMA integrity_check")
    result = check.fetchone()
    if result is None or result[0] != "ok":
        logger.error(
            "SQLite integrity_check failed after relaxing NOT NULL on %s: %r", table, result
        )
