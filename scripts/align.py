#!/usr/bin/env python
"""Manual alignment runner.

Usage:
    uv run python scripts/align.py --item-id li_abc123
    uv run python scripts/align.py --item-id li_abc123 --ebook-file /path/to/book.epub
"""
import argparse
import asyncio
import sys
from pathlib import Path


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run audiobook-ebook forced alignment")
    parser.add_argument("--item-id", required=True, help="Audiobookshelf item ID")
    parser.add_argument(
        "--ebook-file",
        type=Path,
        default=None,
        help="Local EPUB path; overrides ebook_source config",
    )
    args = parser.parse_args()

    from sqlalchemy import select

    from earmark.database import AsyncSessionLocal, init_db
    from earmark.models import AlignmentJob
    from earmark.services.alignment import run_alignment_job

    await init_db()

    job_id: int
    async with AsyncSessionLocal() as session:
        job = AlignmentJob(abs_item_id=args.item_id, status="pending")
        if args.ebook_file:
            ebook_path = args.ebook_file.resolve()
            if not ebook_path.exists():
                print(f"Error: ebook file not found: {ebook_path}", file=sys.stderr)
                return 1
            job.ebook_cache_path = str(ebook_path)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id
        print(f"Created job {job_id} for item {args.item_id}")

    await run_alignment_job(job_id)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AlignmentJob).where(AlignmentJob.id == job_id)
        )
        finished = result.scalar_one()
        print(f"Status: {finished.status}")
        if finished.status == "failed":
            print(f"Error: {finished.error_message}", file=sys.stderr)
            return 1
        print(f"Sync map: {finished.sync_map_path}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
