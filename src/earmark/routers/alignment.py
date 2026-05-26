import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.database import get_session
from earmark.earmark_auth import get_current_earmark_user
from earmark.models import AlignmentJob, User
from earmark.schemas import AlignmentJobCreate, AlignmentJobRead, SyncMapEntry
from earmark.services.alignment import run_alignment_job

router = APIRouter(prefix="/alignment", tags=["alignment"])

_ACTIVE_STATUSES = {
    "pending", "fetching_audio", "fetching_ebook", "parsing_epub", "aligning", "assembling"
}


@router.post("/jobs", response_model=AlignmentJobRead, status_code=202)
async def create_job(
    body: AlignmentJobCreate,
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> AlignmentJob:
    existing = await session.execute(
        select(AlignmentJob).where(
            AlignmentJob.abs_item_id == body.abs_item_id,
            AlignmentJob.status.in_(_ACTIVE_STATUSES),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An active job already exists for this item")

    job = AlignmentJob(abs_item_id=body.abs_item_id, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    asyncio.create_task(run_alignment_job(job.id))

    return job


@router.get("/jobs", response_model=list[AlignmentJobRead])
async def list_jobs(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> list[AlignmentJob]:
    offset = (page - 1) * per_page
    result = await session.execute(
        select(AlignmentJob)
        .order_by(AlignmentJob.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    return list(result.scalars().all())


@router.get("/jobs/{job_id}", response_model=AlignmentJobRead)
async def get_job(
    job_id: int,
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> AlignmentJob:
    result = await session.execute(
        select(AlignmentJob).where(AlignmentJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/sync-map", response_model=list[SyncMapEntry])
async def get_sync_map(
    job_id: int,
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> list[SyncMapEntry]:
    result = await session.execute(
        select(AlignmentJob).where(AlignmentJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("complete", "complete_with_warnings"):
        raise HTTPException(status_code=409, detail="Job not complete")

    sync_map_path = Path(job.sync_map_path)  # type: ignore[arg-type]
    raw = await asyncio.to_thread(sync_map_path.read_text, encoding="utf-8")
    entries = json.loads(raw)
    return [SyncMapEntry(**e) for e in entries]
