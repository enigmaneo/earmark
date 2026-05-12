import asyncio
import hashlib

from sqlalchemy import select

from earmark.database import AsyncSessionLocal, init_db
from earmark.models import ReadingProgress, User


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


USERS = [
    {"username": "testuser", "password": "password"},
    {"username": "alice", "password": "secret"},
]

PROGRESS: list[dict] = [
    {
        "username": "testuser",
        "document": "8b03a82761fae0ee6cd5a23700361e74",
        "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
        "percentage": 0.2082,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
    },
    {
        "username": "testuser",
        "document": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        "progress": "/body/DocFragment[3]/body/p[12]/text()[1].0",
        "percentage": 0.05,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "Dune",
        "authors": "Frank Herbert",
        "filename": "dune.epub",
    },
    {
        "username": "testuser",
        "document": "deadbeefdeadbeefdeadbeefdeadbeef",
        "progress": "/body/DocFragment[40]/body/div[2]/text()[1].99",
        "percentage": 0.91,
        "device": "kindle",
        "device_id": "KINDLE001",
        "title": "Project Hail Mary",
        "authors": "Andy Weir",
        "filename": "project-hail-mary.epub",
    },
    {
        "username": "alice",
        "document": "8b03a82761fae0ee6cd5a23700361e74",
        "progress": "/body/DocFragment[22]/body/div[10]/text()[1].5",
        "percentage": 0.44,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
    },
    {
        "username": "alice",
        "document": "f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0",
        "progress": "/body/DocFragment[1]/body/p[1]/text()[1].0",
        "percentage": 0.01,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "Mistborn",
        "authors": "Brandon Sanderson",
        "filename": "mistborn.epub",
    },
]


async def seed() -> None:
    await init_db()

    async with AsyncSessionLocal() as session:
        # Seed users
        user_map: dict[str, User] = {}
        for u in USERS:
            result = await session.execute(select(User).where(User.username == u["username"]))
            user = result.scalar_one_or_none()
            if user is None:
                user = User(username=u["username"], password_hash=md5(u["password"]))
                session.add(user)
                await session.flush()
                print(f"  Created user: {u['username']}")
            else:
                print(f"  Skipped existing user: {u['username']}")
            user_map[u["username"]] = user

        # Seed progress records
        for p in PROGRESS:
            owner = user_map[p["username"]]
            result = await session.execute(
                select(ReadingProgress).where(
                    ReadingProgress.user_id == owner.id,
                    ReadingProgress.document == p["document"],
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                record = ReadingProgress(
                    user_id=owner.id,
                    document=p["document"],
                    progress=p["progress"],
                    percentage=p["percentage"],
                    device=p["device"],
                    device_id=p["device_id"],
                    filename=p.get("filename"),
                    title=p.get("title"),
                    authors=p.get("authors"),
                )
                session.add(record)
                print(f"  Created progress: {p['title']} for {p['username']}")
            else:
                print(f"  Skipped existing progress: {p['title']} for {p['username']}")

        await session.commit()


def main() -> None:
    print("Seeding database...")
    asyncio.run(seed())
    print("Seeding complete.")


if __name__ == "__main__":
    main()
