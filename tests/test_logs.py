import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from earmark.config import settings


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "kosync_username": email.split("@")[0] + "_web",
            "kosync_password": password,
        },
    )
    res = await client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


@pytest.fixture
async def jwt(client: AsyncClient) -> str:
    return await _register_and_login(client, "alice@example.com", "password123")


@pytest.fixture
def auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _line(level: str, name: str, message: str, timestamp: str) -> str:
    return json.dumps({"timestamp": timestamp, "level": level, "name": name, "message": message})


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def sample_log(log_dir: Path) -> Path:
    path = log_dir / "earmark.log"
    path.write_text(
        "\n".join(
            [
                _line("DEBUG", "earmark.scheduler", "starting sync", "2026-06-14T10:00:00Z"),
                _line("INFO", "earmark.scheduler", "sync complete", "2026-06-14T10:01:00Z"),
                _line("WARNING", "earmark.abs", "abs slow response", "2026-06-14T10:02:00Z"),
                _line("ERROR", "earmark.sync", "write failed", "2026-06-14T10:03:00Z"),
                "this is not json and must be skipped",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


# --- auth ---


async def test_logs_auth_required(client: AsyncClient) -> None:
    assert (await client.get("/web/logs")).status_code == 401
    assert (await client.get("/web/logs/files")).status_code == 401


# --- /web/logs ---


async def test_logs_missing_file_returns_empty(
    client: AsyncClient, auth: dict[str, str], log_dir: Path
) -> None:
    res = await client.get("/web/logs", headers=auth)
    assert res.status_code == 200
    assert res.json() == {"data": [], "total": 0, "page": 1, "per_page": 100}


async def test_logs_lists_newest_first_and_skips_malformed(
    client: AsyncClient, auth: dict[str, str], sample_log: Path
) -> None:
    res = await client.get("/web/logs", headers=auth)
    body = res.json()
    assert body["total"] == 4  # the malformed line is skipped
    assert body["data"][0]["message"] == "write failed"
    assert body["data"][-1]["message"] == "starting sync"


async def test_logs_min_level_filter(
    client: AsyncClient, auth: dict[str, str], sample_log: Path
) -> None:
    res = await client.get("/web/logs?level=WARNING", headers=auth)
    body = res.json()
    assert body["total"] == 2
    assert {e["level"] for e in body["data"]} == {"WARNING", "ERROR"}


async def test_logs_text_search(
    client: AsyncClient, auth: dict[str, str], sample_log: Path
) -> None:
    res = await client.get("/web/logs?q=sync", headers=auth)
    body = res.json()
    # matches "starting sync", "sync complete" (message) and earmark.sync (logger name)
    assert body["total"] == 3


async def test_logs_date_range(client: AsyncClient, auth: dict[str, str], sample_log: Path) -> None:
    res = await client.get(
        "/web/logs?from=2026-06-14T10:01:00Z&to=2026-06-14T10:02:30Z", headers=auth
    )
    body = res.json()
    assert body["total"] == 2
    assert {e["message"] for e in body["data"]} == {"sync complete", "abs slow response"}


async def test_logs_pagination(client: AsyncClient, auth: dict[str, str], sample_log: Path) -> None:
    res = await client.get("/web/logs?per_page=2&page=2", headers=auth)
    body = res.json()
    assert body["total"] == 4
    assert body["page"] == 2
    assert len(body["data"]) == 2
    assert body["data"][0]["message"] == "sync complete"


async def test_logs_rejects_path_traversal(
    client: AsyncClient, auth: dict[str, str], log_dir: Path
) -> None:
    res = await client.get("/web/logs?file=../secret.txt", headers=auth)
    assert res.status_code == 400


# --- /web/logs/files ---


async def test_log_files_empty_when_no_dir(
    client: AsyncClient, auth: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "missing"))
    res = await client.get("/web/logs/files", headers=auth)
    assert res.status_code == 200
    assert res.json() == []


async def test_log_files_lists_rotated(
    client: AsyncClient, auth: dict[str, str], sample_log: Path, log_dir: Path
) -> None:
    (log_dir / "earmark.log.1").write_text("{}\n", encoding="utf-8")
    res = await client.get("/web/logs/files", headers=auth)
    names = {f["name"] for f in res.json()}
    assert names == {"earmark.log", "earmark.log.1"}


async def test_logs_rejects_invalid_level(
    client: AsyncClient, auth: dict[str, str], sample_log: Path
) -> None:
    res = await client.get("/web/logs?level=WARN", headers=auth)
    assert res.status_code == 400


# --- file handler formatting ---


def test_file_handler_emits_utc_timestamp(log_dir: Path) -> None:
    """asctime must be rendered in UTC, matching the literal 'Z' in the timestamp."""
    import logging
    from datetime import UTC, datetime

    from earmark.logging_config import _build_file_handler, log_file_path

    handler = _build_file_handler("size", 10, "midnight", 5)
    record = logging.LogRecord(
        name="earmark.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    # Pin record.created to a known UTC instant so we can assert the rendered value.
    record.created = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC).timestamp()
    handler.emit(record)
    handler.close()

    entry = json.loads(log_file_path().read_text(encoding="utf-8").splitlines()[-1])
    assert entry["timestamp"] == "2026-06-14T12:00:00Z"
