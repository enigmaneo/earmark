import pytest
from httpx import AsyncClient

from conftest import md5


@pytest.fixture
async def earmark_user(client: AsyncClient) -> dict[str, str]:
    await client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "password": "hunter2hunter2",
            "kosync_username": "testko",
            "kosync_password": "kosecret",
        },
    )
    return {"email": "test@example.com", "password": "hunter2hunter2"}


@pytest.fixture
async def auth_token(client: AsyncClient, earmark_user: dict[str, str]) -> str:
    res = await client.post("/auth/login", json=earmark_user)
    return res.json()["access_token"]


async def test_register_creates_user(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/register",
        json={
            "email": "new@example.com",
            "password": "supersecret",
            "kosync_username": "newko",
            "kosync_password": "kopass",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "new@example.com"
    assert "id" in data
    assert "password_hash" not in data


async def test_register_creates_linked_kosync_user(client: AsyncClient) -> None:
    # Registration creates a KosyncUser; KOReader-style auth then works with the same
    # username and x-auth-key = md5(plaintext kosync password).
    res = await client.post(
        "/auth/register",
        json={
            "email": "linked@example.com",
            "password": "supersecret",
            "kosync_username": "linkedko",
            "kosync_password": "kopass",
        },
    )
    assert res.status_code == 201

    auth = await client.get(
        "/users/auth",
        headers={"x-auth-user": "linkedko", "x-auth-key": md5("kopass")},
    )
    assert auth.status_code == 200


async def test_register_adopts_existing_unlinked_kosync_user(client: AsyncClient) -> None:
    # A KosyncUser self-registered by KOReader (unlinked) with progress already recorded.
    hashed = md5("kopass")
    await client.post("/users/create", json={"username": "orphan", "password": hashed})
    headers = {"x-auth-user": "orphan", "x-auth-key": hashed}
    progress = {
        "document": "8b03a82761fae0ee6cd5a23700361e74",
        "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
        "percentage": 0.2082,
        "device": "boox",
        "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
    }
    put = await client.put("/syncs/progress", json=progress, headers=headers)
    assert put.status_code == 200

    # Registering with the same kosync username + matching password adopts that account.
    res = await client.post(
        "/auth/register",
        json={
            "email": "adopter@example.com",
            "password": "supersecret",
            "kosync_username": "orphan",
            "kosync_password": "kopass",
        },
    )
    assert res.status_code == 201

    # The previously-recorded progress is still readable via the (now adopted) kosync account.
    got = await client.get(f"/syncs/progress/{progress['document']}", headers=headers)
    assert got.status_code == 200
    assert got.json()["progress"] == progress["progress"]


async def test_register_rejects_kosync_password_mismatch(client: AsyncClient) -> None:
    await client.post("/users/create", json={"username": "taken", "password": md5("realpass")})
    res = await client.post(
        "/auth/register",
        json={
            "email": "wrong@example.com",
            "password": "supersecret",
            "kosync_username": "taken",
            "kosync_password": "guess",
        },
    )
    assert res.status_code == 409
    # The earmark user must not have been created.
    login = await client.post(
        "/auth/login", json={"email": "wrong@example.com", "password": "supersecret"}
    )
    assert login.status_code == 401


async def test_register_rejects_kosync_username_already_linked(client: AsyncClient) -> None:
    # First registration claims "shared" for one earmark user.
    await client.post(
        "/auth/register",
        json={
            "email": "first@example.com",
            "password": "supersecret",
            "kosync_username": "shared",
            "kosync_password": "kopass",
        },
    )
    # A second registration can't reuse it, even with the correct password.
    res = await client.post(
        "/auth/register",
        json={
            "email": "second@example.com",
            "password": "supersecret",
            "kosync_username": "shared",
            "kosync_password": "kopass",
        },
    )
    assert res.status_code == 409
    login = await client.post(
        "/auth/login", json={"email": "second@example.com", "password": "supersecret"}
    )
    assert login.status_code == 401


async def test_register_duplicate_email(client: AsyncClient, earmark_user: dict[str, str]) -> None:
    res = await client.post(
        "/auth/register",
        json={
            "email": earmark_user["email"],
            "password": "anotherpass",
            "kosync_username": "otherko",
            "kosync_password": "kopass",
        },
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
