import hashlib

import pytest
from httpx import AsyncClient

from conftest import PROGRESS_PAYLOAD

DOC = PROGRESS_PAYLOAD["document"]
DOC2 = "aaaabbbbccccdddd11112222333344445555"


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    await client.post("/auth/register", json={"email": email, "password": password})
    res = await client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


async def _create_kosync_and_link(client: AsyncClient, username: str, token: str) -> dict[str, str]:
    hashed = md5("hunter2")
    await client.post(
        "/users/create",
        json={"username": username, "password": hashed},
        headers={"Authorization": f"Bearer {token}"},
    )
    return {"x-auth-user": username, "x-auth-key": hashed}


@pytest.fixture
async def alice_jwt(client: AsyncClient) -> str:
    return await _register_and_login(client, "alice@example.com", "password123")


@pytest.fixture
async def bob_jwt(client: AsyncClient) -> str:
    return await _register_and_login(client, "bob@example.com", "password123")


@pytest.fixture
async def alice_kosync(client: AsyncClient, alice_jwt: str) -> dict[str, str]:
    return await _create_kosync_and_link(client, "alice_kosync", alice_jwt)


@pytest.fixture
async def bob_kosync(client: AsyncClient, bob_jwt: str) -> dict[str, str]:
    return await _create_kosync_and_link(client, "bob_kosync", bob_jwt)


# --- /web/documents ---


async def test_web_documents_empty(client: AsyncClient, alice_jwt: str) -> None:
    res = await client.get("/web/documents", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert res.status_code == 200
    assert res.json() == []


async def test_web_documents_returns_distinct_docs(
    client: AsyncClient, alice_jwt: str, alice_kosync: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    res = await client.get("/web/documents", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert res.status_code == 200
    docs = res.json()
    assert len(docs) == 1
    assert docs[0]["document"] == DOC


async def test_web_documents_isolation(
    client: AsyncClient,
    alice_jwt: str,
    alice_kosync: dict[str, str],
    bob_jwt: str,
    bob_kosync: dict[str, str],
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    await client.put("/syncs/progress", json={**PROGRESS_PAYLOAD, "document": DOC2}, headers=bob_kosync)

    alice_res = await client.get("/web/documents", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert len(alice_res.json()) == 1
    assert alice_res.json()[0]["document"] == DOC

    bob_res = await client.get("/web/documents", headers={"Authorization": f"Bearer {bob_jwt}"})
    assert len(bob_res.json()) == 1
    assert bob_res.json()[0]["document"] == DOC2


async def test_web_documents_auth_required(client: AsyncClient) -> None:
    res = await client.get("/web/documents")
    assert res.status_code == 401


# --- /web/progress ---


async def test_web_progress_empty(client: AsyncClient, alice_jwt: str) -> None:
    res = await client.get("/web/progress", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert res.status_code == 200
    assert res.json()["total"] == 0


async def test_web_progress_lists_all(
    client: AsyncClient, alice_jwt: str, alice_kosync: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    await client.put("/syncs/progress", json={**PROGRESS_PAYLOAD, "document": DOC2}, headers=alice_kosync)
    res = await client.get("/web/progress", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert res.json()["total"] == 2


async def test_web_progress_filter_by_document(
    client: AsyncClient, alice_jwt: str, alice_kosync: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    await client.put("/syncs/progress", json={**PROGRESS_PAYLOAD, "document": DOC2}, headers=alice_kosync)
    res = await client.get(
        f"/web/progress?document={DOC}", headers={"Authorization": f"Bearer {alice_jwt}"}
    )
    body = res.json()
    assert body["total"] == 1
    assert body["data"][0]["document"] == DOC


async def test_web_progress_sort_ascending(
    client: AsyncClient, alice_jwt: str, alice_kosync: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json={**PROGRESS_PAYLOAD, "percentage": 0.1, "progress": "/body/DocFragment[1]/body/p[1]"}, headers=alice_kosync)
    await client.put("/syncs/progress", json={**PROGRESS_PAYLOAD, "percentage": 0.9, "progress": "/body/DocFragment[2]/body/p[1]"}, headers=alice_kosync)
    res = await client.get(
        "/web/progress?sort_by=percentage&sort_dir=asc",
        headers={"Authorization": f"Bearer {alice_jwt}"},
    )
    data = res.json()["data"]
    assert data[0]["percentage"] < data[1]["percentage"]


async def test_web_progress_isolation(
    client: AsyncClient,
    alice_jwt: str,
    alice_kosync: dict[str, str],
    bob_kosync: dict[str, str],
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=bob_kosync)
    res = await client.get("/web/progress", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert res.json()["total"] == 1


async def test_web_progress_auth_required(client: AsyncClient) -> None:
    res = await client.get("/web/progress")
    assert res.status_code == 401


# --- /web/records/{id} ---


async def test_web_delete_record(
    client: AsyncClient, alice_jwt: str, alice_kosync: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    list_res = await client.get("/web/progress", headers={"Authorization": f"Bearer {alice_jwt}"})
    record_id = list_res.json()["data"][0]["id"]

    del_res = await client.delete(
        f"/web/records/{record_id}", headers={"Authorization": f"Bearer {alice_jwt}"}
    )
    assert del_res.status_code == 200
    assert del_res.json() == {"deleted": record_id}

    list_after = await client.get("/web/progress", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert list_after.json()["total"] == 0


async def test_web_delete_record_not_found(client: AsyncClient, alice_jwt: str) -> None:
    res = await client.delete("/web/records/99999", headers={"Authorization": f"Bearer {alice_jwt}"})
    assert res.status_code == 404


async def test_web_delete_record_ownership(
    client: AsyncClient,
    alice_jwt: str,
    alice_kosync: dict[str, str],
    bob_jwt: str,
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice_kosync)
    list_res = await client.get("/web/progress", headers={"Authorization": f"Bearer {alice_jwt}"})
    record_id = list_res.json()["data"][0]["id"]

    res = await client.delete(
        f"/web/records/{record_id}", headers={"Authorization": f"Bearer {bob_jwt}"}
    )
    assert res.status_code == 404


async def test_web_delete_record_auth_required(client: AsyncClient) -> None:
    res = await client.delete("/web/records/1")
    assert res.status_code == 401
