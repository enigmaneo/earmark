import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from earmark.earmark_auth import get_current_earmark_user
from earmark.logging_config import LOG_FILENAME, log_dir
from earmark.models import User
from earmark.schemas import LogEntry, LogFileInfo, LogList

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web", tags=["logs"])

# Level name -> numeric value, for "minimum level" filtering.
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_log_file(name: str) -> Path:
    """Resolve a requested file name to a path inside the log dir, rejecting traversal."""
    base = log_dir().resolve()
    candidate = (base / name).resolve()
    if candidate.parent != base:
        raise HTTPException(status_code=400, detail="Invalid log file")
    return candidate


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _entry_time(entry: dict[str, object]) -> datetime | None:
    raw = entry.get("timestamp")
    return _parse_iso(raw) if isinstance(raw, str) else None


@router.get("/logs/files", response_model=list[LogFileInfo])
async def list_log_files(
    _user: User = Depends(get_current_earmark_user),
) -> list[LogFileInfo]:
    base = log_dir()
    if not base.exists():
        return []
    files = [p for p in base.glob(f"{LOG_FILENAME}*") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        LogFileInfo(
            name=p.name,
            size_bytes=p.stat().st_size,
            modified_at=datetime.fromtimestamp(p.stat().st_mtime, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        )
        for p in files
    ]


@router.get("/logs", response_model=LogList)
async def list_logs(
    _user: User = Depends(get_current_earmark_user),
    file: str = Query(default=LOG_FILENAME),
    level: str | None = Query(default=None),
    q: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=1, le=200),
) -> LogList:
    path = _resolve_log_file(file)
    if not path.exists():
        return LogList(data=[], total=0, page=page, per_page=per_page)

    min_level = _LEVELS.get(level.upper()) if level else None
    needle = q.lower() if q else None
    from_dt = _parse_iso(from_) if from_ else None
    to_dt = _parse_iso(to) if to else None

    matches: list[dict[str, object]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue

            if min_level is not None:
                entry_level = str(entry.get("level", "")).upper()
                if _LEVELS.get(entry_level, logging.NOTSET) < min_level:
                    continue

            if needle is not None:
                haystack = f"{entry.get('message', '')} {entry.get('name', '')}".lower()
                if needle not in haystack:
                    continue

            if from_dt is not None or to_dt is not None:
                ts = _entry_time(entry)
                if ts is None:
                    continue
                if from_dt is not None and ts < from_dt:
                    continue
                if to_dt is not None and ts > to_dt:
                    continue

            matches.append(entry)

    matches.reverse()  # newest first
    total = len(matches)
    start = (page - 1) * per_page
    window = matches[start : start + per_page]
    data = [
        LogEntry(
            timestamp=(e.get("timestamp") if isinstance(e.get("timestamp"), str) else None),
            level=(e.get("level") if isinstance(e.get("level"), str) else None),
            name=(e.get("name") if isinstance(e.get("name"), str) else None),
            message=str(e.get("message", "")),
        )
        for e in window
    ]
    return LogList(data=data, total=total, page=page, per_page=per_page)
