import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select, text

from earmark.database import AsyncSessionLocal, Base, engine, init_db
from earmark.earmark_auth import hash_password, kosync_hash
from earmark.models import AbsEbookMapping, AbsLibraryItem, KosyncUser, ReadingProgress, User


def md5(value: str) -> str:
    return kosync_hash(value)


ABS_LIBRARY_ITEMS = [
    {
        "abs_item_id": "li_notw",
        "library_id": "lib_main",
        "title": "The Name of the Wind",
        "author": "Patrick Rothfuss",
        "ebook_filename": "name-of-the-wind.epub",
        "ebook_format": "epub",
        "audio_file_count": 40,
        "total_duration_seconds": 27000.0,
    },
    {
        "abs_item_id": "li_dune",
        "library_id": "lib_main",
        "title": "Dune",
        "author": "Frank Herbert",
        "ebook_filename": "dune.epub",
        "ebook_format": "epub",
        "audio_file_count": 56,
        "total_duration_seconds": 21600.0,
    },
    {
        "abs_item_id": "li_mistborn",
        "library_id": "lib_main",
        "title": "Mistborn",
        "author": "Brandon Sanderson",
        "ebook_filename": "mistborn.epub",
        "ebook_format": "epub",
        "audio_file_count": 35,
        "total_duration_seconds": 24600.0,
    },
    {
        "abs_item_id": "li_hyperion",
        "library_id": "lib_main",
        "title": "Hyperion",
        "author": "Dan Simmons",
        "ebook_filename": "hyperion.epub",
        "ebook_format": "epub",
        "audio_file_count": 28,
        "total_duration_seconds": 18000.0,
    },
    {
        "abs_item_id": "li_foundation",
        "library_id": "lib_main",
        "title": "Foundation",
        "author": "Isaac Asimov",
        "ebook_filename": "foundation.epub",
        "ebook_format": "epub",
        "audio_file_count": 14,
        "total_duration_seconds": 14400.0,
    },
    {
        "abs_item_id": "li_neuromancer",
        "library_id": "lib_main",
        "title": "Neuromancer",
        "author": "William Gibson",
        "ebook_filename": "neuromancer.epub",
        "ebook_format": "epub",
        "audio_file_count": 22,
        "total_duration_seconds": 14400.0,
    },
    {
        "abs_item_id": "li_enders_game",
        "library_id": "lib_main",
        "title": "Ender's Game",
        "author": "Orson Scott Card",
        "ebook_filename": "enders-game.epub",
        "ebook_format": "epub",
        "audio_file_count": 19,
        "total_duration_seconds": 14400.0,
    },
]

EARMARK_USERS = [
    {"email": "testuser@example.com", "password": "password"},
    {"email": "alice@example.com", "password": "secret"},
    {"email": "bob@example.com", "password": "hunter2"},
    {"email": "carol@example.com", "password": "carol123"},
]

KOSYNC_USERS = [
    {"username": "testuser", "password": "password", "earmark_email": "testuser@example.com"},
    {"username": "alice", "password": "secret", "earmark_email": "alice@example.com"},
    {"username": "bob", "password": "hunter2", "earmark_email": "bob@example.com"},
    {"username": "carol", "password": "carol123", "earmark_email": "carol@example.com"},
]

# Document hash constants for readability
DOC_NAME_OF_THE_WIND = "8b03a82761fae0ee6cd5a23700361e74"
DOC_DUNE = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
DOC_PROJECT_HAIL_MARY = "deadbeefdeadbeefdeadbeefdeadbeef"
DOC_MISTBORN = "f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0"
DOC_HYPERION = "1a2b3c4d5e6f1a2b3c4d5e6f1a2b3c4d"
DOC_FOUNDATION = "aaaabbbbccccddddaaaabbbbccccdddd"
DOC_NEUROMANCER = "1111222233334444111122223333444"
DOC_ENDERS_GAME = "abcdef0123456789abcdef0123456789"

ABS_EBOOK_MAPPINGS: list[dict] = [
    {
        "earmark_email": "testuser@example.com",
        "abs_item_id": "li_notw",
        "abs_title": "The Name of the Wind",
        "abs_author": "Patrick Rothfuss",
        "ebook_path": "name-of-the-wind.epub",
        "ebook_filename": "name-of-the-wind.epub",
        "kosync_document": DOC_NAME_OF_THE_WIND,
    },
    {
        "earmark_email": "testuser@example.com",
        "abs_item_id": "li_dune",
        "abs_title": "Dune",
        "abs_author": "Frank Herbert",
        "ebook_path": "dune.epub",
        "ebook_filename": "dune.epub",
        "kosync_document": DOC_DUNE,
    },
    {
        "earmark_email": "alice@example.com",
        "abs_item_id": "li_notw",
        "abs_title": "The Name of the Wind",
        "abs_author": "Patrick Rothfuss",
        "ebook_path": "name-of-the-wind.epub",
        "ebook_filename": "name-of-the-wind.epub",
        "kosync_document": DOC_NAME_OF_THE_WIND,
    },
    {
        "earmark_email": "alice@example.com",
        "abs_item_id": "li_mistborn",
        "abs_title": "Mistborn",
        "abs_author": "Brandon Sanderson",
        "ebook_path": "mistborn.epub",
        "ebook_filename": "mistborn.epub",
        "kosync_document": DOC_MISTBORN,
    },
]

PROGRESS: list[dict] = [
    # --- testuser: Name of the Wind (3 entries across devices) ---
    {
        "username": "testuser",
        "document": DOC_NAME_OF_THE_WIND,
        "progress": "/body/DocFragment[8]/body/div[12]/text()[1].0",
        "percentage": 0.10,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
        "is_latest": False,
    },
    {
        "username": "testuser",
        "document": DOC_NAME_OF_THE_WIND,
        "progress": "/body/DocFragment[12]/body/div[44]/text()[1].20",
        "percentage": 0.15,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
        "is_latest": False,
    },
    {
        "username": "testuser",
        "document": DOC_NAME_OF_THE_WIND,
        "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
        "percentage": 0.2082,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
        "is_latest": True,
    },
    # --- testuser: Dune (3 entries) ---
    {
        "username": "testuser",
        "document": DOC_DUNE,
        "progress": "/body/DocFragment[1]/body/p[2]/text()[1].0",
        "percentage": 0.02,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "Dune",
        "authors": "Frank Herbert",
        "filename": "dune.epub",
        "is_latest": False,
    },
    {
        "username": "testuser",
        "document": DOC_DUNE,
        "progress": "/body/DocFragment[2]/body/p[8]/text()[1].0",
        "percentage": 0.04,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "Dune",
        "authors": "Frank Herbert",
        "filename": "dune.epub",
        "is_latest": False,
    },
    {
        "username": "testuser",
        "document": DOC_DUNE,
        "progress": "/body/DocFragment[3]/body/p[12]/text()[1].0",
        "percentage": 0.05,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
        "title": "Dune",
        "authors": "Frank Herbert",
        "filename": "dune.epub",
        "is_latest": True,
    },
    # --- alice: Name of the Wind (3 entries) ---
    {
        "username": "alice",
        "document": DOC_NAME_OF_THE_WIND,
        "progress": "/body/DocFragment[10]/body/div[3]/text()[1].0",
        "percentage": 0.22,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
        "is_latest": False,
    },
    {
        "username": "alice",
        "document": DOC_NAME_OF_THE_WIND,
        "progress": "/body/DocFragment[16]/body/div[7]/text()[1].2",
        "percentage": 0.33,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
        "is_latest": False,
    },
    {
        "username": "alice",
        "document": DOC_NAME_OF_THE_WIND,
        "progress": "/body/DocFragment[22]/body/div[10]/text()[1].5",
        "percentage": 0.44,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "The Name of the Wind",
        "authors": "Patrick Rothfuss",
        "filename": "name-of-the-wind.epub",
        "is_latest": True,
    },
    # --- alice: Mistborn (3 entries) ---
    {
        "username": "alice",
        "document": DOC_MISTBORN,
        "progress": "/body/DocFragment[1]/body/p[1]/text()[1].0",
        "percentage": 0.01,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "Mistborn",
        "authors": "Brandon Sanderson",
        "filename": "mistborn.epub",
        "is_latest": False,
    },
    {
        "username": "alice",
        "document": DOC_MISTBORN,
        "progress": "/body/DocFragment[5]/body/p[3]/text()[1].0",
        "percentage": 0.08,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "Mistborn",
        "authors": "Brandon Sanderson",
        "filename": "mistborn.epub",
        "is_latest": False,
    },
    {
        "username": "alice",
        "document": DOC_MISTBORN,
        "progress": "/body/DocFragment[11]/body/p[6]/text()[1].0",
        "percentage": 0.19,
        "device": "kobo",
        "device_id": "KOBO001",
        "title": "Mistborn",
        "authors": "Brandon Sanderson",
        "filename": "mistborn.epub",
        "is_latest": True,
    },
    # --- bob: Hyperion (3 entries) ---
    {
        "username": "bob",
        "document": DOC_HYPERION,
        "progress": "/body/DocFragment[4]/body/div[2]/text()[1].0",
        "percentage": 0.12,
        "device": "kindle",
        "device_id": "KINDLE002",
        "title": "Hyperion",
        "authors": "Dan Simmons",
        "filename": "hyperion.epub",
        "is_latest": False,
    },
    {
        "username": "bob",
        "document": DOC_HYPERION,
        "progress": "/body/DocFragment[9]/body/div[5]/text()[1].0",
        "percentage": 0.28,
        "device": "kindle",
        "device_id": "KINDLE002",
        "title": "Hyperion",
        "authors": "Dan Simmons",
        "filename": "hyperion.epub",
        "is_latest": False,
    },
    {
        "username": "bob",
        "document": DOC_HYPERION,
        "progress": "/body/DocFragment[18]/body/div[11]/text()[1].3",
        "percentage": 0.51,
        "device": "kindle",
        "device_id": "KINDLE002",
        "title": "Hyperion",
        "authors": "Dan Simmons",
        "filename": "hyperion.epub",
        "is_latest": True,
    },
    # --- bob: Foundation (3 entries) ---
    {
        "username": "bob",
        "document": DOC_FOUNDATION,
        "progress": "/body/DocFragment[2]/body/p[4]/text()[1].0",
        "percentage": 0.07,
        "device": "kindle",
        "device_id": "KINDLE002",
        "title": "Foundation",
        "authors": "Isaac Asimov",
        "filename": "foundation.epub",
        "is_latest": False,
    },
    {
        "username": "bob",
        "document": DOC_FOUNDATION,
        "progress": "/body/DocFragment[6]/body/p[9]/text()[1].0",
        "percentage": 0.21,
        "device": "kindle",
        "device_id": "KINDLE002",
        "title": "Foundation",
        "authors": "Isaac Asimov",
        "filename": "foundation.epub",
        "is_latest": False,
    },
    {
        "username": "bob",
        "document": DOC_FOUNDATION,
        "progress": "/body/DocFragment[14]/body/p[2]/text()[1].0",
        "percentage": 0.47,
        "device": "kindle",
        "device_id": "KINDLE002",
        "title": "Foundation",
        "authors": "Isaac Asimov",
        "filename": "foundation.epub",
        "is_latest": True,
    },
    # --- carol: Neuromancer (3 entries) ---
    {
        "username": "carol",
        "document": DOC_NEUROMANCER,
        "progress": "/body/DocFragment[3]/body/div[1]/text()[1].0",
        "percentage": 0.09,
        "device": "boox",
        "device_id": "BOOX_CAROL",
        "title": "Neuromancer",
        "authors": "William Gibson",
        "filename": "neuromancer.epub",
        "is_latest": False,
    },
    {
        "username": "carol",
        "document": DOC_NEUROMANCER,
        "progress": "/body/DocFragment[7]/body/div[4]/text()[1].0",
        "percentage": 0.31,
        "device": "boox",
        "device_id": "BOOX_CAROL",
        "title": "Neuromancer",
        "authors": "William Gibson",
        "filename": "neuromancer.epub",
        "is_latest": False,
    },
    {
        "username": "carol",
        "document": DOC_NEUROMANCER,
        "progress": "/body/DocFragment[13]/body/div[8]/text()[1].15",
        "percentage": 0.63,
        "device": "boox",
        "device_id": "BOOX_CAROL",
        "title": "Neuromancer",
        "authors": "William Gibson",
        "filename": "neuromancer.epub",
        "is_latest": True,
    },
    # --- carol: Ender's Game (3 entries) ---
    {
        "username": "carol",
        "document": DOC_ENDERS_GAME,
        "progress": "/body/DocFragment[2]/body/p[5]/text()[1].0",
        "percentage": 0.06,
        "device": "boox",
        "device_id": "BOOX_CAROL",
        "title": "Ender's Game",
        "authors": "Orson Scott Card",
        "filename": "enders-game.epub",
        "is_latest": False,
    },
    {
        "username": "carol",
        "document": DOC_ENDERS_GAME,
        "progress": "/body/DocFragment[8]/body/p[3]/text()[1].0",
        "percentage": 0.38,
        "device": "boox",
        "device_id": "BOOX_CAROL",
        "title": "Ender's Game",
        "authors": "Orson Scott Card",
        "filename": "enders-game.epub",
        "is_latest": False,
    },
    {
        "username": "carol",
        "document": DOC_ENDERS_GAME,
        "progress": "/body/DocFragment[20]/body/p[11]/text()[1].0",
        "percentage": 0.75,
        "device": "boox",
        "device_id": "BOOX_CAROL",
        "title": "Ender's Game",
        "authors": "Orson Scott Card",
        "filename": "enders-game.epub",
        "is_latest": True,
    },
]


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # Also clear Alembic's bookkeeping so init_db re-runs migrations from scratch.
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
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
                is_latest=p.get("is_latest", True),
                updated_at=datetime.now(UTC),
            )
            session.add(record)
            print(f"  Created progress: {p['title']} for {p['username']}")

        # Seed abs_library_items
        abs_item_map: dict[str, AbsLibraryItem] = {}
        for li in ABS_LIBRARY_ITEMS:
            result = await session.execute(
                select(AbsLibraryItem).where(AbsLibraryItem.abs_item_id == li["abs_item_id"])
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = AbsLibraryItem(
                    abs_item_id=li["abs_item_id"],
                    library_id=li["library_id"],
                    title=li["title"],
                    author=li.get("author"),
                    ebook_filename=li.get("ebook_filename"),
                    ebook_format=li.get("ebook_format"),
                    audio_file_count=li["audio_file_count"],
                    total_duration_seconds=li["total_duration_seconds"],
                    raw_metadata=json.dumps({}),
                )
                session.add(row)
                await session.flush()
                print(f"  Created abs_library_item: {li['title']}")
            else:
                print(f"  Skipped existing abs_library_item: {li['title']}")
            abs_item_map[li["abs_item_id"]] = row

        # Seed abs_ebook_mappings
        for m in ABS_EBOOK_MAPPINGS:
            owner = earmark_user_map.get(m["earmark_email"])
            if owner is None:
                continue
            result = await session.execute(
                select(AbsEbookMapping).where(
                    AbsEbookMapping.user_id == owner.id,
                    AbsEbookMapping.abs_item_id == m["abs_item_id"],
                    AbsEbookMapping.ebook_path == m["ebook_path"],
                )
            )
            if result.scalar_one_or_none() is None:
                session.add(
                    AbsEbookMapping(
                        user_id=owner.id,
                        abs_item_id=m["abs_item_id"],
                        abs_title=m["abs_title"],
                        abs_author=m.get("abs_author"),
                        ebook_path=m["ebook_path"],
                        ebook_filename=m["ebook_filename"],
                        kosync_document=m.get("kosync_document"),
                    )
                )
                print(
                    f"  Created mapping: {m['abs_title']} → "
                    f"{m['ebook_filename']} ({m['earmark_email']})"
                )
            else:
                print(f"  Skipped existing mapping: {m['abs_title']} ({m['earmark_email']})")

        await session.commit()


def main() -> None:
    print("Seeding database...")
    asyncio.run(seed())
    print("Seeding complete.")


if __name__ == "__main__":
    main()
