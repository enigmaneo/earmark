#!/usr/bin/env python
"""End-to-end integration test for the earmark alignment pipeline.

Connects to a real Audiobookshelf server and runs forced alignment using a
local EPUB file. Prints real-time stage progress and a sync map preview on
completion.

Usage:
    uv run python testing/test_alignment.py --item-id li_abc123 --ebook-file /path/to/book.epub

See testing/README.md for full setup instructions.
"""
import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

STAGE_LABELS = {
    "pending": "Pending",
    "fetching_audio": "Fetching audio files from ABS",
    "fetching_ebook": "Fetching ebook",
    "parsing_epub": "Parsing EPUB and extracting paragraphs",
    "aligning": "Running WhisperX transcription + alignment",
    "assembling": "Assembling sync map",
    "complete": "Complete",
    "complete_with_warnings": "Complete (with warnings)",
    "failed": "FAILED",
}


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


async def _poll_progress(
    job_id: int,
    session_factory,
    stop_event: asyncio.Event,
    interval: float = 2.0,
) -> None:
    from sqlalchemy import select

    from earmark.models import AlignmentJob

    last_status: str | None = None
    last_paragraph_count: int | None = None
    last_fragment_count: int | None = None

    while True:
        async with session_factory() as session:
            result = await session.execute(
                select(AlignmentJob).where(AlignmentJob.id == job_id)
            )
            job = result.scalar_one()

        now = _fmt_ts(datetime.now(UTC))
        status = job.status

        if status != last_status:
            label = STAGE_LABELS.get(status, status)
            print(f"  [{now}] {label}")
            last_status = status

        if job.paragraph_count is not None and job.paragraph_count != last_paragraph_count:
            print(f"           Paragraphs extracted: {job.paragraph_count:,}")
            last_paragraph_count = job.paragraph_count

        if job.fragment_count is not None and job.fragment_count != last_fragment_count:
            print(f"           Fragments aligned:    {job.fragment_count:,}")
            last_fragment_count = job.fragment_count

        if stop_event.is_set():
            break

        await asyncio.sleep(interval)


def _print_sync_map_preview(sync_map_path: Path, n: int = 10) -> None:
    with open(sync_map_path) as f:
        entries = json.load(f)

    total = len(entries)
    preview = entries[:n]

    id_w, start_w, end_w, pos_w, text_w = 10, 10, 10, 38, 45
    sep = "-" * (id_w + start_w + end_w + pos_w + text_w + 8)

    print(
        f"  {'ID':<{id_w}} {'Start':<{start_w}} {'End':<{end_w}} "
        f"{'EPUB position':<{pos_w}} {'Text preview':<{text_w}}"
    )
    print(f"  {sep}")

    for entry in preview:
        id_ = str(entry.get("id", ""))[:id_w]
        start = f"{entry.get('audio_start', 0):.2f}s"
        end = f"{entry.get('audio_end', 0):.2f}s"
        pos = str(entry.get("ebook_pos", ""))[:pos_w]
        snippet = str(entry.get("text_snippet", ""))
        if len(snippet) > text_w:
            snippet = snippet[: text_w - 1] + "…"
        print(
            f"  {id_:<{id_w}} {start:<{start_w}} {end:<{end_w}} "
            f"{pos:<{pos_w}} {snippet:<{text_w}}"
        )

    if total > n:
        print(f"  ... and {total - n:,} more entries")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a real end-to-end alignment and print progress + results."
    )
    parser.add_argument("--item-id", required=True, help="Audiobookshelf item ID")
    parser.add_argument(
        "--ebook-file",
        type=Path,
        required=True,
        help="Local EPUB file to use for alignment",
    )
    args = parser.parse_args()

    ebook_path = args.ebook_file.resolve()
    if not ebook_path.exists():
        print(f"Error: ebook file not found: {ebook_path}", file=sys.stderr)
        return 1

    from sqlalchemy import select

    from earmark.database import AsyncSessionLocal, init_db
    from earmark.models import AlignmentJob
    from earmark.services.alignment import run_alignment_job

    print("Initializing database...")
    await init_db()

    async with AsyncSessionLocal() as session:
        job = AlignmentJob(
            abs_item_id=args.item_id,
            status="pending",
            ebook_cache_path=str(ebook_path),
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    print(f"Created alignment job #{job_id} for item {args.item_id!r}")
    print(f"EPUB: {ebook_path}")
    print()
    print("Pipeline progress:")

    start_time = datetime.now(UTC)
    stop_event = asyncio.Event()

    pipeline_task = asyncio.create_task(
        run_alignment_job(job_id, session_factory=AsyncSessionLocal)
    )
    poll_task = asyncio.create_task(
        _poll_progress(job_id, AsyncSessionLocal, stop_event)
    )

    try:
        await pipeline_task
    except Exception as exc:
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
    finally:
        stop_event.set()
        await poll_task

    elapsed = (datetime.now(UTC) - start_time).total_seconds()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AlignmentJob).where(AlignmentJob.id == job_id)
        )
        finished = result.scalar_one()

    print()
    if finished.status == "failed":
        print(f"FAILED after {_fmt_duration(elapsed)}")
        print(f"Error: {finished.error_message}", file=sys.stderr)
        return 1

    print(f"Completed in {_fmt_duration(elapsed)}")
    print()
    print("Job statistics:")
    print(f"  Paragraphs : {finished.paragraph_count:,}")
    print(f"  Fragments  : {finished.fragment_count:,}")
    if (
        finished.paragraph_count is not None
        and finished.fragment_count is not None
        and finished.paragraph_count != finished.fragment_count
    ):
        diff = abs(finished.paragraph_count - finished.fragment_count)
        print(f"  Mismatch   : {diff} (sync map truncated to min)")
    print(f"  Duration   : {_fmt_duration(elapsed)}")
    print(f"  Sync map   : {finished.sync_map_path}")
    print()
    print("Sync map preview (first 10 entries):")
    if finished.sync_map_path:
        _print_sync_map_preview(Path(finished.sync_map_path))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
