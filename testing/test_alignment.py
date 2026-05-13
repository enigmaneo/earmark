import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from earmark.services.alignment import run_alignment_job


# ── fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def jwt_headers(client: AsyncClient) -> dict[str, str]:
    await client.post("/auth/register", json={"email": "align@example.com", "password": "secret"})
    resp = await client.post("/auth/login", json={"email": "align@example.com", "password": "secret"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


ABS_ITEM_ID = "li_test123"

ABS_METADATA: dict[str, Any] = {
    "id": ABS_ITEM_ID,
    "libraryId": "lib_001",
    "updatedAt": 1715000000000,
    "media": {
        "metadata": {"title": "Test Book", "authorName": "Test Author"},
        "audioFiles": [
            {
                "index": 1,
                "metadata": {"filename": "chapter01.mp3"},
                "filename": "chapter01.mp3",
                "duration": 100.0,
            },
        ],
        "ebookFile": {"filename": "test.epub", "ext": ".epub"},
    },
}

FAKE_PARAGRAPHS = ["First paragraph.", "Second paragraph."]
FAKE_INDEX = {
    "para_000": {"text": "First paragraph.", "ebook_pos": "/body/DocFragment[1]/body/p[1]"},
    "para_001": {"text": "Second paragraph.", "ebook_pos": "/body/DocFragment[1]/body/p[2]"},
}
FAKE_FRAGMENTS: list[dict[str, str]] = [
    {"begin": "0.000", "end": "3.500"},
    {"begin": "3.500", "end": "7.200"},
]


async def _run_pipeline(
    job_id: int,
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
    cache_dir: Path,
) -> None:
    """Run the full pipeline with all blocking calls mocked."""

    async def fake_get_item(self: Any, item_id: str) -> dict[str, Any]:
        return ABS_METADATA

    async def fake_download_audio(self: Any, item_id: str, filename: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake_audio")

    async def fake_download_ebook(self: Any, item_id: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake_epub")

    def fake_parse_epub(epub_path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
        return FAKE_PARAGRAPHS, FAKE_INDEX

    def fake_ffmpeg_concat(audio_files: list[Path], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake_wav")

    def fake_run_aeneas(
        audio_path: Path, paragraphs_path: Path, raw_output_path: Path
    ) -> list[dict[str, str]]:
        raw_output_path.write_text(
            json.dumps({"fragments": FAKE_FRAGMENTS}), encoding="utf-8"
        )
        return FAKE_FRAGMENTS

    with (
        patch(
            "earmark.services.audiobookshelf.AudiobookshelfClient.get_item",
            fake_get_item,
        ),
        patch(
            "earmark.services.audiobookshelf.AudiobookshelfClient.download_audio_file",
            fake_download_audio,
        ),
        patch(
            "earmark.services.audiobookshelf.AudiobookshelfClient.download_ebook",
            fake_download_ebook,
        ),
        patch("earmark.services.alignment._parse_epub_sync", fake_parse_epub),
        patch("earmark.services.alignment._ffmpeg_concat_sync", fake_ffmpeg_concat),
        patch("earmark.services.alignment._run_aeneas_sync", fake_run_aeneas),
        patch("earmark.config.settings.alignment_cache_dir", str(cache_dir)),
    ):
        await run_alignment_job(job_id, session_factory=session_factory)


# ── tests ──────────────────────────────────────────────────────────────────────


async def test_create_job_returns_202(client: AsyncClient, jwt_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["abs_item_id"] == ABS_ITEM_ID
    assert data["status"] == "pending"
    assert data["id"] is not None


async def test_create_job_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID})
    assert resp.status_code in (401, 403)


async def test_create_job_duplicate_active_returns_409(
    client: AsyncClient, jwt_headers: dict[str, str]
) -> None:
    await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    assert resp.status_code == 409


async def test_get_job_not_found(client: AsyncClient, jwt_headers: dict[str, str]) -> None:
    resp = await client.get("/alignment/jobs/9999", headers=jwt_headers)
    assert resp.status_code == 404


async def test_get_sync_map_not_found(client: AsyncClient, jwt_headers: dict[str, str]) -> None:
    resp = await client.get("/alignment/jobs/9999/sync-map", headers=jwt_headers)
    assert resp.status_code == 404


async def test_get_sync_map_returns_409_while_pending(
    client: AsyncClient, jwt_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    job_id = resp.json()["id"]
    resp = await client.get(f"/alignment/jobs/{job_id}/sync-map", headers=jwt_headers)
    assert resp.status_code == 409


async def test_list_jobs(client: AsyncClient, jwt_headers: dict[str, str]) -> None:
    await client.post(
        "/alignment/jobs", json={"abs_item_id": "li_aaa"}, headers=jwt_headers
    )
    resp = await client.get("/alignment/jobs", headers=jwt_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


async def test_list_jobs_pagination(client: AsyncClient, jwt_headers: dict[str, str]) -> None:
    for i in range(3):
        await client.post(
            "/alignment/jobs", json={"abs_item_id": f"li_{i:03d}"}, headers=jwt_headers
        )
    resp = await client.get("/alignment/jobs?page=1&per_page=2", headers=jwt_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_full_pipeline_happy_path(
    client: AsyncClient,
    jwt_headers: dict[str, str],
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
    tmp_path: Path,
) -> None:
    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    await _run_pipeline(job_id, db_session_factory, tmp_path)

    resp = await client.get(f"/alignment/jobs/{job_id}", headers=jwt_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "complete"

    resp = await client.get(f"/alignment/jobs/{job_id}/sync-map", headers=jwt_headers)
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    assert entries[0]["id"] == "para_000"
    assert entries[0]["audio_start"] == 0.0
    assert entries[0]["ebook_pos"] == "/body/DocFragment[1]/body/p[1]"


async def test_pipeline_fails_on_abs_error(
    client: AsyncClient,
    jwt_headers: dict[str, str],
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
    tmp_path: Path,
) -> None:
    import httpx as _httpx

    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": "li_bad"}, headers=jwt_headers
    )
    job_id = resp.json()["id"]

    async def bad_get_item(self: Any, item_id: str) -> dict[str, Any]:
        raise _httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        )

    with (
        patch(
            "earmark.services.audiobookshelf.AudiobookshelfClient.get_item",
            bad_get_item,
        ),
        patch("earmark.config.settings.alignment_cache_dir", str(tmp_path)),
    ):
        await run_alignment_job(job_id, session_factory=db_session_factory)

    resp = await client.get(f"/alignment/jobs/{job_id}", headers=jwt_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_message"] is not None
