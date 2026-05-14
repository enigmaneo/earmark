from httpx import AsyncClient

from conftest import md5


async def test_create_user(client: AsyncClient) -> None:
    response = await client.post("/users/create", json={"username": "alice", "password": "hunter2"})
    assert response.status_code == 201
    assert response.json() == {"username": "alice"}


async def test_create_user_duplicate(client: AsyncClient) -> None:
    await client.post("/users/create", json={"username": "alice", "password": "hunter2"})
    response = await client.post("/users/create", json={"username": "alice", "password": "other"})
    assert response.status_code == 402


async def test_auth_valid(client: AsyncClient, alice: dict[str, str]) -> None:
    response = await client.get("/users/auth", headers=alice)
    assert response.status_code == 200
    assert response.json() == {"authorized": "OK"}


async def test_auth_wrong_password(client: AsyncClient) -> None:
    await client.post("/users/create", json={"username": "alice", "password": "hunter2"})
    response = await client.get(
        "/users/auth",
        headers={"x-auth-user": "alice", "x-auth-key": md5("wrongpassword")},
    )
    assert response.status_code == 401


async def test_auth_unknown_user(client: AsyncClient) -> None:
    response = await client.get(
        "/users/auth",
        headers={"x-auth-user": "nobody", "x-auth-key": md5("anything")},
    )
    assert response.status_code == 401


async def test_auth_missing_headers(client: AsyncClient) -> None:
    response = await client.get("/users/auth")
    assert response.status_code == 422
