# Alignment Pipeline Testing Guide

This document explains how to run and extend the tests for the audiobook-ebook forced alignment pipeline.

## Test file location

```
testing/test_alignment.py
```

The tests live in `testing/` alongside the Bruno API collection. They run with the same `pytest` invocation as the rest of the test suite.

## Running the tests

```bash
# All tests (unit + alignment)
uv run pytest

# Alignment tests only
uv run pytest testing/test_alignment.py -v

# A single test
uv run pytest testing/test_alignment.py::test_full_pipeline_happy_path -v
```

## What is tested

| Test | What it covers |
|------|----------------|
| `test_create_job_returns_202` | POST /alignment/jobs creates a job at status `pending`, returns HTTP 202 |
| `test_create_job_requires_auth` | Unauthenticated request is rejected (401/403) |
| `test_create_job_duplicate_active_returns_409` | A second job for the same item while one is active returns 409 |
| `test_get_job_not_found` | GET /alignment/jobs/9999 returns 404 |
| `test_get_sync_map_not_found` | GET sync-map for unknown job returns 404 |
| `test_get_sync_map_returns_409_while_pending` | Sync-map endpoint returns 409 until the job is complete |
| `test_list_jobs` | GET /alignment/jobs returns a list |
| `test_list_jobs_pagination` | `page` / `per_page` query params are respected |
| `test_full_pipeline_happy_path` | Full end-to-end run with all I/O mocked; sync-map entries are correct |
| `test_pipeline_fails_on_abs_error` | An ABS API error sets `status=failed` with an `error_message` |

## How mocking works

The pipeline has several external dependencies that cannot run in CI:

- **Audiobookshelf API** — HTTP calls via `AudiobookshelfClient`
- **EPUB parsing** — `ebooklib` + `BeautifulSoup` (blocking, reads real files)
- **ffmpeg** — audio concatenation
- **aeneas** — forced alignment engine (requires system packages; see [Dependencies](#dependencies))

All of these are replaced with lightweight fakes inside `_run_pipeline()` using `unittest.mock.patch`. The fakes write small dummy files to `tmp_path` so the pipeline's file-handling logic is still exercised.

The pipeline is run **directly** (not over HTTP) by calling `run_alignment_job(job_id, session_factory=db_session_factory)`. Passing the test session factory ensures the pipeline reads and writes to the same in-memory SQLite database that the HTTP client is using.

## Fixtures

The test uses three fixtures from `conftest.py` (root level):

| Fixture | What it provides |
|---------|-----------------|
| `client` | `httpx.AsyncClient` wired to the FastAPI app with an in-memory SQLite DB |
| `db_session_factory` | The `async_sessionmaker` used by `client`; passed directly to `run_alignment_job` |
| `tmp_path` | Pytest built-in; used as the alignment cache directory so nothing touches the real filesystem |

`jwt_headers` is a local fixture defined in `test_alignment.py` itself. It registers a test user and returns a `{"Authorization": "Bearer ..."}` header dict.

## Adding a new test

```python
async def test_my_scenario(
    client: AsyncClient,
    jwt_headers: dict[str, str],
    db_session_factory: async_sessionmaker,
    tmp_path: Path,
) -> None:
    # 1. Create a job via HTTP
    resp = await client.post(
        "/alignment/jobs", json={"abs_item_id": "li_myitem"}, headers=jwt_headers
    )
    job_id = resp.json()["id"]

    # 2. Run the pipeline with mocks
    await _run_pipeline(job_id, db_session_factory, tmp_path)

    # 3. Assert final state
    resp = await client.get(f"/alignment/jobs/{job_id}", headers=jwt_headers)
    assert resp.json()["status"] == "complete"
```

To test a failure scenario, patch only the step you want to break and call `run_alignment_job` directly instead of `_run_pipeline`.

## Manual end-to-end testing

For a real run against a live Audiobookshelf instance, use the CLI script:

```bash
# Uses ebook_source from .env (default: "abs")
uv run python scripts/align.py --item-id li_abc123

# Supply an ebook file directly (skips ebook download)
uv run python scripts/align.py --item-id li_abc123 --ebook-file /path/to/book.epub
```

The script prints status at each stage and exits 0 on success, 1 on failure.

## Dependencies

`aeneas` cannot be installed via `uv` (it requires `numpy` as a build-time dependency and has no pre-built wheel for Python 3.12+). Install it manually before running the pipeline for real:

```bash
pip install numpy
pip install aeneas
```

System packages also required:

```bash
# macOS
brew install ffmpeg espeak

# Debian/Ubuntu
apt-get install ffmpeg espeak
```

The test suite **does not** require aeneas to be installed — the `_run_aeneas_sync` function is mocked in all tests.
