import asyncio

import earmark.models  # noqa: F401 — registers all models with Base.metadata
from earmark.database import Base, engine, init_db


async def reset() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()


def main() -> None:
    print("Resetting database...")
    asyncio.run(reset())
    print("Done. Database is empty and ready.")


if __name__ == "__main__":
    main()
