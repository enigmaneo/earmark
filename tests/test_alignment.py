import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from bs4 import BeautifulSoup

from earmark.models import AlignmentJob
from earmark.services.alignment import (
    _element_full_xpath,
    recover_orphaned_jobs,
    run_alignment_job,
)
from sqlalchemy import select


# ── _element_full_xpath ────────────────────────────────────────────────────────


def _find(html: str, tag: str, **kwargs: str) -> object:
    return BeautifulSoup(html, "html.parser").find(tag, **kwargs)


def test_element_full_xpath_direct_child_of_body() -> None:
    html = "<html><body><p>text</p></body></html>"
    el = BeautifulSoup(html, "html.parser").find("p")
    assert _element_full_xpath(el) == "/body/p[1]"


def test_element_full_xpath_sibling_index() -> None:
    html = "<html><body><p>one</p><p>two</p><p>three</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    ps = soup.find_all("p")
    assert _element_full_xpath(ps[0]) == "/body/p[1]"
    assert _element_full_xpath(ps[1]) == "/body/p[2]"
    assert _element_full_xpath(ps[2]) == "/body/p[3]"


def test_element_full_xpath_nested_structure() -> None:
    html = "<html><body><section><div><p>text</p></div></section></body></html>"
    el = BeautifulSoup(html, "html.parser").find("p")
    assert _element_full_xpath(el) == "/body/section[1]/div[1]/p[1]"


def test_element_full_xpath_mixed_siblings() -> None:
    html = (
        "<html><body>"
        "<section><div><p>a</p><p>b</p></div><div><p>c</p></div></section>"
        "</body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")
    ps = soup.find_all("p")
    assert _element_full_xpath(ps[0]) == "/body/section[1]/div[1]/p[1]"
    assert _element_full_xpath(ps[1]) == "/body/section[1]/div[1]/p[2]"
    assert _element_full_xpath(ps[2]) == "/body/section[1]/div[2]/p[1]"


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
                "ino": "test_ino_001",
                "metadata": {"filename": "chapter01.mp3"},
                "filename": "chapter01.mp3",
                "duration": 100.0,
            },
        ],
        "chapters": [
            {"id": 0, "start": 0.0, "end": 10.0, "title": "Intro"},
            {"id": 1, "start": 10.0, "end": 100.0, "title": "Content"},
        ],
        "ebookFile": {"filename": "test.epub", "ext": ".epub"},
    },
}

FAKE_PARAGRAPHS = ["First paragraph.", "Second paragraph."]
FAKE_INDEX = {
    "para_000": {"text": "First paragraph.", "ebook_pos": "/body/DocFragment[1]/body/section[1]/p[1]"},
    "para_001": {"text": "Second paragraph.", "ebook_pos": "/body/DocFragment[1]/body/section[1]/p[2]"},
}
FAKE_FRAGMENTS: list[dict[str, str]] = [
    {"begin": "0.000", "end": "3.500"},
    {"begin": "3.500", "end": "7.200"},
]


async def _run_pipeline(
    job_id: int,
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
    cache_dir: Path,
    abs_metadata_override: dict[str, Any] | None = None,
    paragraphs_override: list[str] | None = None,
    index_override: dict[str, dict[str, str]] | None = None,
    fragments_override: list[dict[str, str]] | None = None,
) -> None:
    """Run the full pipeline with all blocking calls mocked."""
    metadata = abs_metadata_override if abs_metadata_override is not None else ABS_METADATA
    paragraphs = paragraphs_override if paragraphs_override is not None else FAKE_PARAGRAPHS
    index = index_override if index_override is not None else FAKE_INDEX
    fragments = fragments_override if fragments_override is not None else FAKE_FRAGMENTS

    async def fake_get_item(self: Any, item_id: str) -> dict[str, Any]:
        return metadata

    async def fake_download_audio(self: Any, item_id: str, filename: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake_audio")

    async def fake_download_ebook(self: Any, item_id: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake_epub")

    def fake_parse_epub(epub_path: Path) -> tuple[list[str], dict[str, dict[str, str]], int]:
        return paragraphs, index, 1

    def fake_ffmpeg_concat(audio_files: list[Path], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake_wav")

    def fake_ffmpeg_trim(input_path: Path, output_path: Path, start: float) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake_wav_trimmed")

    async def fake_run_aeneas(
        self: Any,
        cache_dir: Path,
        audio_path: Path,
        paragraphs: list[str],
    ) -> list[dict[str, str]]:
        return fragments

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
        patch("earmark.services.alignment._ffmpeg_trim_sync", fake_ffmpeg_trim),
        patch("earmark.services.alignment.AlignmentPipeline._run_aeneas", fake_run_aeneas),
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
    assert entries[0]["audio_start"] == 10.0  # 0.0 + 10.0 offset from chapter[1].start
    assert entries[0]["ebook_pos"] == "/body/DocFragment[1]/body/section[1]/p[1]"

    resp = await client.get(f"/alignment/jobs/{job_id}", headers=jwt_headers)
    assert resp.json()["audio_offset_seconds"] == 10.0


async def test_pipeline_no_offset_without_chapters(
    client: AsyncClient,
    jwt_headers: dict[str, str],
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
    tmp_path: Path,
) -> None:
    metadata_no_chapters = copy.deepcopy(ABS_METADATA)
    del metadata_no_chapters["media"]["chapters"]

    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    job_id = resp.json()["id"]

    await _run_pipeline(job_id, db_session_factory, tmp_path, abs_metadata_override=metadata_no_chapters)

    resp = await client.get(f"/alignment/jobs/{job_id}/sync-map", headers=jwt_headers)
    entries = resp.json()
    assert entries[0]["audio_start"] == 0.0

    resp = await client.get(f"/alignment/jobs/{job_id}", headers=jwt_headers)
    assert resp.json()["audio_offset_seconds"] is None


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


async def test_pipeline_assigns_fragments_in_seq_order_with_1000plus_paragraphs(
    client: AsyncClient,
    jwt_headers: dict[str, str],
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
    tmp_path: Path,
) -> None:
    """Books with ≥1000 paragraphs must not use lexicographic id sort (para_1000 < para_101)."""
    n = 1100
    paragraphs = [f"Paragraph {i}." for i in range(n)]
    index = {
        f"para_{i:03d}": {
            "text": f"Paragraph {i}.",
            "ebook_pos": f"/body/DocFragment[1]/body/section[1]/p[{i + 1}]",
        }
        for i in range(n)
    }
    # fragment i covers seconds i..i+1 — distinct per paragraph
    fragments = [{"begin": f"{i}.0", "end": f"{i + 1}.0"} for i in range(n)]

    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    job_id = resp.json()["id"]

    await _run_pipeline(
        job_id,
        db_session_factory,
        tmp_path,
        paragraphs_override=paragraphs,
        index_override=index,
        fragments_override=fragments,
    )

    resp = await client.get(f"/alignment/jobs/{job_id}/sync-map", headers=jwt_headers)
    entries = resp.json()
    assert len(entries) == n

    # fragment[i]'s timestamp must land on para_{i:03d}, not on the lex-i-th id.
    # 10.0 is the chapter[1].start offset from ABS_METADATA.
    for i, entry in enumerate(entries):
        assert entry["id"] == f"para_{i:03d}", f"position {i}: got {entry['id']}"
        assert entry["audio_start"] == pytest.approx(i + 10.0)
        assert entry["audio_end"] == pytest.approx(i + 1 + 10.0)


async def test_pipeline_drops_degenerate_fragments(
    client: AsyncClient,
    jwt_headers: dict[str, str],
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
    tmp_path: Path,
) -> None:
    """Fragments aeneas couldn't align (begin == end) must be dropped from the sync map."""
    paragraphs = ["First.", "Second.", "Third (back matter)."]
    index = {
        "para_000": {"text": "First.", "ebook_pos": "/body/DocFragment[1]/body/section[1]/p[1]"},
        "para_001": {"text": "Second.", "ebook_pos": "/body/DocFragment[1]/body/section[1]/p[2]"},
        "para_002": {
            "text": "Third (back matter).",
            "ebook_pos": "/body/DocFragment[2]/body/section[1]/p[1]",
        },
    }
    fragments = [
        {"begin": "0.000", "end": "3.500"},
        {"begin": "3.500", "end": "7.200"},
        {"begin": "90.000", "end": "90.000"},  # aeneas placed at audio end — unaligned
    ]

    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": ABS_ITEM_ID}, headers=jwt_headers
    )
    job_id = resp.json()["id"]

    await _run_pipeline(
        job_id,
        db_session_factory,
        tmp_path,
        paragraphs_override=paragraphs,
        index_override=index,
        fragments_override=fragments,
    )

    resp = await client.get(f"/alignment/jobs/{job_id}/sync-map", headers=jwt_headers)
    entries = resp.json()
    assert len(entries) == 2
    assert [e["id"] for e in entries] == ["para_000", "para_001"]
    assert all(e["audio_start"] != e["audio_end"] for e in entries)


async def test_recover_orphaned_jobs_marks_active_as_failed(
    db_session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    async with db_session_factory() as session:
        for status in ("pending", "fetching_audio", "aligning"):
            session.add(AlignmentJob(
                abs_item_id="li_orphan", status=status, progress=5,
            ))
        session.add(AlignmentJob(
            abs_item_id="li_done", status="complete", progress=100,
        ))
        await session.commit()

    n = await recover_orphaned_jobs(session_factory=db_session_factory)
    assert n == 3

    async with db_session_factory() as session:
        result = await session.execute(select(AlignmentJob))
        jobs = list(result.scalars().all())
        statuses = sorted(j.status for j in jobs)
        assert statuses == ["complete", "failed", "failed", "failed"]
        for j in jobs:
            if j.status == "failed":
                assert j.error_message == "Interrupted by server restart"
