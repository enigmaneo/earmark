import pytest
from httpx import AsyncClient

from tests.conftest import PROGRESS_PAYLOAD, md5

DOC = PROGRESS_PAYLOAD["document"]


async def test_put_progress_creates_record(client: AsyncClient, alice: dict[str, str]) -> None:
    response = await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    assert response.status_code == 200
    data = response.json()
    assert data["document"] == DOC
    assert data["percentage"] == pytest.approx(0.2082)
    assert data["device"] == "boox"
    assert "timestamp" in data


async def test_put_progress_updates_when_higher(
    client: AsyncClient, alice: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    higher = {**PROGRESS_PAYLOAD, "percentage": 0.5, "progress": "/body/div[2]"}
    response = await client.put("/syncs/progress", json=higher, headers=alice)
    assert response.status_code == 200
    assert response.json()["percentage"] == pytest.approx(0.5)
    assert response.json()["progress"] == "/body/div[2]"


async def test_put_progress_furthest_wins(client: AsyncClient, alice: dict[str, str]) -> None:
    high = {**PROGRESS_PAYLOAD, "percentage": 0.9, "progress": "/body/div[99]"}
    await client.put("/syncs/progress", json=high, headers=alice)
    lower = {**PROGRESS_PAYLOAD, "percentage": 0.1, "progress": "/body/div[1]"}
    response = await client.put("/syncs/progress", json=lower, headers=alice)
    assert response.status_code == 200
    assert response.json()["percentage"] == pytest.approx(0.9)
    assert response.json()["progress"] == "/body/div[99]"


async def test_put_progress_with_metadata(client: AsyncClient, alice: dict[str, str]) -> None:
    payload = {
        **PROGRESS_PAYLOAD,
        "metadata": {
            "filename": "gatsby.epub",
            "title": "The Great Gatsby",
            "authors": "F. Scott Fitzgerald",
        },
    }
    await client.put("/syncs/progress", json=payload, headers=alice)
    response = await client.get(f"/syncs/progress/{DOC}", headers=alice)
    # The GET single-record endpoint does not return metadata fields,
    # but the list endpoint does.
    list_response = await client.get("/syncs/progress", headers=alice)
    item = list_response.json()["data"][0]
    assert item["filename"] == "gatsby.epub"
    assert item["title"] == "The Great Gatsby"
    assert item["authors"] == "F. Scott Fitzgerald"


async def test_get_progress(client: AsyncClient, alice: dict[str, str]) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    response = await client.get(f"/syncs/progress/{DOC}", headers=alice)
    assert response.status_code == 200
    assert response.json()["document"] == DOC


async def test_get_progress_not_found(client: AsyncClient, alice: dict[str, str]) -> None:
    response = await client.get("/syncs/progress/nonexistent", headers=alice)
    assert response.status_code == 404


async def test_list_progress(client: AsyncClient, alice: dict[str, str]) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    response = await client.get("/syncs/progress", headers=alice)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert len(body["data"]) == 1


async def test_list_progress_pagination(client: AsyncClient, alice: dict[str, str]) -> None:
    for i in range(5):
        payload = {**PROGRESS_PAYLOAD, "document": f"doc{i}", "percentage": i * 0.1}
        await client.put("/syncs/progress", json=payload, headers=alice)
    response = await client.get("/syncs/progress?page=1&per_page=3", headers=alice)
    body = response.json()
    assert body["total"] == 5
    assert body["per_page"] == 3
    assert len(body["data"]) == 3


async def test_delete_progress(client: AsyncClient, alice: dict[str, str]) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    response = await client.delete(f"/syncs/progress/{DOC}", headers=alice)
    assert response.status_code == 200
    assert response.json() == {"deleted": DOC}
    assert (await client.get(f"/syncs/progress/{DOC}", headers=alice)).status_code == 404


async def test_delete_progress_not_found(client: AsyncClient, alice: dict[str, str]) -> None:
    response = await client.delete("/syncs/progress/nonexistent", headers=alice)
    assert response.status_code == 404


async def test_put_progress_auth_required(client: AsyncClient) -> None:
    response = await client.put("/syncs/progress", json=PROGRESS_PAYLOAD)
    assert response.status_code == 422


async def test_get_progress_auth_required(client: AsyncClient) -> None:
    response = await client.get(f"/syncs/progress/{DOC}")
    assert response.status_code == 422


async def test_list_progress_auth_required(client: AsyncClient) -> None:
    response = await client.get("/syncs/progress")
    assert response.status_code == 422


async def test_delete_progress_auth_required(client: AsyncClient) -> None:
    response = await client.delete(f"/syncs/progress/{DOC}")
    assert response.status_code == 422
