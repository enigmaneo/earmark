import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from conftest import PROGRESS_PAYLOAD
from earmark.services.epub import validate_progress_position

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
    higher = {**PROGRESS_PAYLOAD, "percentage": 0.5}
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
        payload = {**PROGRESS_PAYLOAD, "percentage": i * 0.1}
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


def _make_minimal_epub(tmp_path: Path) -> Path:
    """Write a tiny but valid EPUB with one spine document to tmp_path."""
    epub_path = tmp_path / "test.epub"
    content_doc = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml">'
        "<head><title>T</title></head>"
        "<body><div><p>Hello</p><p>World</p></div><section><p>In section</p></section></body>"
        "</html>"
    )
    container_xml = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        "<rootfiles>"
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title>'
        '<dc:identifier id="uid">test-id</dc:identifier></metadata>'
        '<manifest><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="ch1"/></spine>'
        "</package>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/ch1.xhtml", content_doc)
    epub_path.write_bytes(buf.getvalue())
    return epub_path


def test_validate_progress_position_valid(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    # spine_pos=1, first div, first p
    assert validate_progress_position(epub, "/body/DocFragment[1]/body/div[1]/p[1]") is True


def test_validate_progress_position_text_node(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    assert validate_progress_position(epub, "/body/DocFragment[1]/body/div[1]/p[1]/text()[1].5") is True


def test_validate_progress_position_out_of_bounds_spine(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    assert validate_progress_position(epub, "/body/DocFragment[99]/body/div[1]/p[1]") is False


def test_validate_progress_position_missing_element(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    # There is no p[99] in div[1]
    assert validate_progress_position(epub, "/body/DocFragment[1]/body/div[1]/p[99]") is False


def test_validate_progress_position_bad_format(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    assert validate_progress_position(epub, "/body/div[1]") is False


def test_validate_progress_position_bare_tag(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    # section has no [1] index — bare tag should default to index 1
    assert validate_progress_position(epub, "/body/DocFragment[1]/body/section/p[1]") is True


def test_validate_progress_position_text_no_bracket(tmp_path: Path) -> None:
    epub = _make_minimal_epub(tmp_path)
    # KOReader sometimes emits /text().171 without [n] before the offset
    assert validate_progress_position(epub, "/body/DocFragment[1]/body/div[1]/p[1]/text().5") is True


async def test_put_progress_invalid_position_rejected(
    client: AsyncClient, alice: dict[str, str], tmp_path: Path
) -> None:
    epub = _make_minimal_epub(tmp_path)
    with patch(
        "earmark.routers.progress.find_epub_for_document",
        new=AsyncMock(return_value=epub),
    ):
        response = await client.put(
            "/syncs/progress",
            json={**PROGRESS_PAYLOAD, "progress": "/body/DocFragment[9999]/body/p[1]"},
            headers=alice,
        )
    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


async def test_put_progress_valid_position_accepted(
    client: AsyncClient, alice: dict[str, str], tmp_path: Path
) -> None:
    epub = _make_minimal_epub(tmp_path)
    with patch(
        "earmark.routers.progress.find_epub_for_document",
        new=AsyncMock(return_value=epub),
    ):
        response = await client.put(
            "/syncs/progress",
            json={**PROGRESS_PAYLOAD, "progress": "/body/DocFragment[1]/body/div[1]/p[1]"},
            headers=alice,
        )
    assert response.status_code == 200


async def test_put_progress_no_epub_mapping_accepted(
    client: AsyncClient, alice: dict[str, str]
) -> None:
    with patch(
        "earmark.routers.progress.find_epub_for_document",
        new=AsyncMock(return_value=None),
    ):
        response = await client.put("/syncs/progress", json=PROGRESS_PAYLOAD, headers=alice)
    assert response.status_code == 200
