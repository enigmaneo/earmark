import hashlib

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from earmark.database import Base, get_session
from earmark.main import app
from earmark.ratelimit import limiter

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    # The login/register limiter would otherwise trip across the many requests a
    # single test client makes from one address. Rate limiting is exercised
    # separately; disable it for the rest of the suite.
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture
async def db_session_factory():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_session_factory: async_sessionmaker):  # type: ignore[type-arg]
    async def override_get_session() -> AsyncSession:  # type: ignore[return]
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


@pytest.fixture
async def alice(client: AsyncClient) -> dict[str, str]:
    # KOReader sends the MD5 of the password as the "password" on registration,
    # and the same hash as x-auth-key on subsequent requests.
    hashed = md5("hunter2")
    await client.post("/users/create", json={"username": "alice", "password": hashed})
    return {"x-auth-user": "alice", "x-auth-key": hashed}


PROGRESS_PAYLOAD = {
    "document": "8b03a82761fae0ee6cd5a23700361e74",
    "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
    "percentage": 0.2082,
    "device": "boox",
    "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
}
