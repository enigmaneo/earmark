import asyncio
import hashlib

from sqlalchemy import select

from earmark.database import AsyncSessionLocal, init_db
from earmark.earmark_auth import hash_password
from earmark.models import KosyncUser, ReadingProgress, User


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


EARMARK_USERS = [
    {"email": "testuser@example.com", "password": "password"},
    {"email": "alice@example.com", "password": "secret"},
]

KOSYNC_USERS = [
    {"username": "testuser", "password": "password", "earmark_email": "testuser@example.com"},
    {"username": "alice", "password": "secret", "earmark_email": "alice@example.com"},
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
        # Seed earmark users
        earmark_user_map: dict[str, User] = {}
        for eu in EARMARK_USERS:
            result = await session.execute(select(User).where(User.email == eu["email"]))
            user = result.scalar_one_or_none()
            if user is None:
                user = User(email=eu["email"], password_hash=hash_password(eu["password"]))
                session.add(user)
                await session.flush()
                print(f"  Created earmark user: {eu['email']}")
            else:
                print(f"  Skipped existing earmark user: {eu['email']}")
            earmark_user_map[eu["email"]] = user

        # Seed kosync users
        kosync_user_map: dict[str, KosyncUser] = {}
        for ku in KOSYNC_USERS:
            result = await session.execute(
                select(KosyncUser).where(KosyncUser.username == ku["username"])
            )
            kuser = result.scalar_one_or_none()
            earmark_owner = earmark_user_map.get(ku["earmark_email"])
            if kuser is None:
                kuser = KosyncUser(
                    username=ku["username"],
                    password_hash=md5(ku["password"]),
                    user_id=earmark_owner.id if earmark_owner else None,
                )
                session.add(kuser)
                await session.flush()
                print(f"  Created kosync user: {ku['username']}")
            else:
                print(f"  Skipped existing kosync user: {ku['username']}")
            kosync_user_map[ku["username"]] = kuser

        # Seed progress records
        for p in PROGRESS:
            owner = kosync_user_map[p["username"]]
            result = await session.execute(
                select(ReadingProgress).where(
                    ReadingProgress.kosync_user_id == owner.id,
                    ReadingProgress.document == p["document"],
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                record = ReadingProgress(
                    kosync_user_id=owner.id,
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
