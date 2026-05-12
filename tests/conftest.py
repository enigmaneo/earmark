import hashlib

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from earmark.database import Base, get_session
from earmark.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session():  # type: ignore[return]
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


@pytest.fixture
async def alice(client: AsyncClient) -> dict[str, str]:
    await client.post("/users/create", json={"username": "alice", "password": "hunter2"})
    return {"x-auth-user": "alice", "x-auth-key": md5("hunter2")}


PROGRESS_PAYLOAD = {
    "document": "8b03a82761fae0ee6cd5a23700361e74",
    "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
    "percentage": 0.2082,
    "device": "boox",
    "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
}
