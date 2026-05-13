import pytest
from httpx import AsyncClient


@pytest.fixture
async def earmark_user(client: AsyncClient) -> dict[str, str]:
    await client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "hunter2hunter2"},
    )
    return {"email": "test@example.com", "password": "hunter2hunter2"}


@pytest.fixture
async def auth_token(client: AsyncClient, earmark_user: dict[str, str]) -> str:
    res = await client.post("/auth/login", json=earmark_user)
    return res.json()["access_token"]


async def test_register_creates_user(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "supersecret"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "new@example.com"
    assert "id" in data
    assert "password_hash" not in data


async def test_register_duplicate_email(client: AsyncClient, earmark_user: dict[str, str]) -> None:
    res = await client.post(
        "/auth/register",
        json={"email": earmark_user["email"], "password": "anotherpass"},
    )
    assert res.status_code == 400


async def test_login_success(client: AsyncClient, earmark_user: dict[str, str]) -> None:
    res = await client.post("/auth/login", json=earmark_user)
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient, earmark_user: dict[str, str]) -> None:
    res = await client.post(
        "/auth/login",
        json={"email": earmark_user["email"], "password": "wrongpassword"},
    )
    assert res.status_code == 401


async def test_login_unknown_email(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "doesnotmatter"},
    )
    assert res.status_code == 401


async def test_me_authenticated(client: AsyncClient, auth_token: str) -> None:
    res = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "test@example.com"


async def test_me_unauthenticated(client: AsyncClient) -> None:
    res = await client.get("/auth/me")
    assert res.status_code in (401, 403)


async def test_me_invalid_token(client: AsyncClient) -> None:
    res = await client.get(
        "/auth/me",
        headers={"Authorization": "Bearer notavalidtoken"},
    )
    assert res.status_code == 401
