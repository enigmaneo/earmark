import asyncio

from sqlalchemy import text

import earmark.models  # noqa: F401 — registers all models with Base.metadata
from earmark.database import Base, engine, init_db


async def reset() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # Also clear Alembic's bookkeeping so init_db re-runs migrations from scratch.
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await init_db()


def main() -> None:
    print("Resetting database...")
    asyncio.run(reset())
    print("Done. Database is empty and ready.")


if __name__ == "__main__":
    main()
