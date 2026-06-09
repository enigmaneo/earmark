import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import PROGRESS_PAYLOAD
from earmark.models import AbsEbookMapping, User

DOC = PROGRESS_PAYLOAD["document"]


async def test_put_progress_creates_record(client: AsyncClient, alice: dict[str, str]) -> None:
    response = await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    assert response.status_code == 200
    data = response.json()
    assert data["document"] == DOC
    assert data["percentage"] == pytest.approx(0.2082)
    assert data["device"] == "boox"
    assert "timestamp" in data


async def test_put_progress_creates_new_record_on_repeat(
    client: AsyncClient, alice: dict[str, str]
) -> None:
    await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    higher = {**PROGRESS_PAYLOAD, "percentage": 0.5, "progress": "/body/div[2]"}
    response = await client.put("/syncs/progress", json=higher, headers=alice)
    assert response.status_code == 200
    assert response.json()["percentage"] == pytest.approx(0.5)
    assert response.json()["progress"] == "/body/div[2]"
    # GET returns the latest entry, not the first
    get_response = await client.get(f"/syncs/progress/{DOC}", headers=alice)
    assert get_response.json()["percentage"] == pytest.approx(0.5)


async def test_put_progress_lower_percentage_still_becomes_latest(
    client: AsyncClient, alice: dict[str, str]
) -> None:
    high = {**PROGRESS_PAYLOAD, "percentage": 0.9, "progress": "/body/div[99]"}
    await client.put("/syncs/progress", json=high, headers=alice)
    lower = {**PROGRESS_PAYLOAD, "percentage": 0.1, "progress": "/body/div[1]"}
    response = await client.put("/syncs/progress", json=lower, headers=alice)
    assert response.status_code == 200
    assert response.json()["percentage"] == pytest.approx(0.1)
    assert response.json()["progress"] == "/body/div[1]"


async def test_put_progress_same_xpath_lower_percentage_is_noop(
    client: AsyncClient, alice: dict[str, str]
) -> None:
    high = {**PROGRESS_PAYLOAD, "percentage": 0.9, "progress": "/body/div[99]"}
    await client.put("/syncs/progress", json=high, headers=alice)
    lower = {**PROGRESS_PAYLOAD, "percentage": 0.1, "progress": "/body/div[99]"}
    response = await client.put("/syncs/progress", json=lower, headers=alice)
    assert response.status_code == 200
    assert response.json()["percentage"] == pytest.approx(0.9)
    assert response.json()["progress"] == "/body/div[99]"
    list_response = await client.get(f"/syncs/progress?document={DOC}", headers=alice)
    assert list_response.json()["total"] == 1


async def test_put_progress_with_duplicate_mapping_documents(
    client: AsyncClient,
    alice: dict[str, str],
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    # The same ebook can be mapped more than once, so kosync_document is not unique.
    # A push for a duplicated document must not crash on MultipleResultsFound.
    async with db_session_factory() as session:
        user = User(email="dup@example.com", password_hash="x")
        session.add(user)
        await session.flush()
        for i in range(2):
            session.add(
                AbsEbookMapping(
                    user_id=user.id,
                    abs_item_id=f"item-{i}",
                    abs_title=f"Book {i}",
                    ebook_path=f"book{i}.epub",
                    kosync_document=DOC,
                )
            )
        await session.commit()

    response = await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    assert response.status_code == 200

    # The lowest-id mapping wins the title deterministically.
    list_response = await client.get(f"/syncs/progress?document={DOC}", headers=alice)
    assert list_response.json()["data"][0]["title"] == "Book 0"


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
    await client.get(f"/syncs/progress/{DOC}", headers=alice)
    # The GET single-record endpoint does not return metadata fields,
    # but the list endpoint does.
    list_response = await client.get(f"/syncs/progress?document={DOC}", headers=alice)
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
    # A second PUT for the same document creates a new historical entry
    higher = {**PROGRESS_PAYLOAD, "percentage": 0.5, "progress": "/body/DocFragment[20]/body/div[1]"}
    await client.put("/syncs/progress", json=higher, headers=alice)
    response = await client.get(f"/syncs/progress?document={DOC}", headers=alice)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert len(body["data"]) == 2
    # Most recent entry comes first
    assert body["data"][0]["percentage"] == pytest.approx(0.5)
    assert body["data"][1]["percentage"] == pytest.approx(0.2082)


async def test_list_progress_pagination(client: AsyncClient, alice: dict[str, str]) -> None:
    # Create 5 entries for the same document
    for i in range(5):
        payload = {**PROGRESS_PAYLOAD, "percentage": i * 0.1, "progress": f"/body/DocFragment[{i+1}]/body/p[1]"}
        await client.put("/syncs/progress", json=payload, headers=alice)
    response = await client.get(f"/syncs/progress?document={DOC}&page=1&per_page=3", headers=alice)
    body = response.json()
    assert body["total"] == 5
    assert body["per_page"] == 3
    assert len(body["data"]) == 3
    # Page 2
    response = await client.get(f"/syncs/progress?document={DOC}&page=2&per_page=3", headers=alice)
    body = response.json()
    assert len(body["data"]) == 2


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
    response = await client.get(f"/syncs/progress?document={DOC}")
    assert response.status_code == 422


async def test_delete_progress_auth_required(client: AsyncClient) -> None:
    response = await client.delete(f"/syncs/progress/{DOC}")
    assert response.status_code == 422
