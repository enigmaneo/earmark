import asyncio
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.config import settings
from earmark.database import get_session
from earmark.earmark_auth import get_current_earmark_user
from earmark.models import AbsEbookMapping, AbsLibraryItem, AlignmentJob, EbookMetadataCache, KosyncUser, ReadingProgress, User
from earmark.schemas import AbsItemSummary, EbookFileSummary, MappingCreate, MappingRead
from earmark.utils import partial_md5
from earmark.services.alignment import ACTIVE_STATUSES, run_alignment_job
from earmark.services.progress import backfill_progress_titles
from earmark.services.audiobookshelf import AudiobookshelfClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web", tags=["mappings"])

_EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw3"}


def _check_cache_intact(abs_item_id: str, lib_item: AbsLibraryItem | None) -> bool | None:
    if lib_item is None or lib_item.abs_updated_at is None:
        return None
    sentinel = Path(settings.alignment_cache_dir) / abs_item_id / ".abs_updated_at"
    if not sentinel.exists():
        return False
    return sentinel.read_text().strip() == lib_item.abs_updated_at.isoformat()


def _mapping_to_schema(
    m: AbsEbookMapping,
    lib_item: AbsLibraryItem | None,
    reading_percentage: float | None = None,
) -> MappingRead:
    job = m.alignment_job
    return MappingRead(
        id=m.id,
        user_id=m.user_id,
        abs_item_id=m.abs_item_id,
        abs_title=m.abs_title,
        abs_author=m.abs_author,
        ebook_path=m.ebook_path,
        ebook_filename=m.ebook_filename,
        kosync_document=m.kosync_document,
        created_at=m.created_at,
        alignment_job_id=job.id if job else None,
        sync_status=job.status if job else None,
        sync_progress=job.progress if job else None,
        sync_error=job.error_message if job else None,
        cache_intact=_check_cache_intact(m.abs_item_id, lib_item),
        reading_percentage=reading_percentage,
    )


def _extract_epub_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        title = book.get_metadata("DC", "title")
        author = book.get_metadata("DC", "creator")
        return (
            title[0][0] if title else None,
            author[0][0] if author else None,
        )
    except Exception:
        logger.warning("Failed to extract EPUB metadata from %s", path, exc_info=True)
        return None, None


def _extract_pdf_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        info = reader.metadata
        if info is None:
            return None, None
        return info.title or None, info.author or None
    except Exception:
        logger.warning("Failed to extract PDF metadata from %s", path, exc_info=True)
        return None, None


@router.get("/abs-items", response_model=list[AbsItemSummary])
async def list_abs_items(
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> list[AbsItemSummary]:
    if settings.audiobookshelf_url and settings.audiobookshelf_api_key:
        try:
            client = AudiobookshelfClient()
            try:
                libraries = await client.list_libraries()
                items: list[AbsItemSummary] = []
                for lib in libraries:
                    raw_items = await client.list_library_items(lib["id"])
                    for item in raw_items:
                        if item.get("mediaType") != "book":
                            continue
                        metadata = item.get("media", {}).get("metadata", {})
                        items.append(
                            AbsItemSummary(
                                abs_item_id=item["id"],
                                title=metadata.get("title", item["id"]),
                                author=metadata.get("authorName") or None,
                            )
                        )
                return items
            finally:
                await client.close()
        except Exception:
            logger.error(
                "Failed to fetch library items from Audiobookshelf at %s",
                settings.audiobookshelf_url,
                exc_info=True,
            )
            raise HTTPException(
                status_code=503, detail="Failed to fetch library items from Audiobookshelf"
            )

    result = await session.execute(select(AbsLibraryItem).order_by(AbsLibraryItem.title))
    rows = result.scalars().all()
    return [
        AbsItemSummary(abs_item_id=r.abs_item_id, title=r.title, author=r.author) for r in rows
    ]


@router.get("/ebook-files", response_model=list[EbookFileSummary])
async def list_ebook_files(
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> list[EbookFileSummary]:
    root_str = settings.ebook_local_root
    if not root_str:
        return []
    root = Path(root_str)
    if not root.is_dir():
        return []

    cache_result = await session.execute(select(EbookMetadataCache))
    cache_map: dict[str, EbookMetadataCache] = {
        row.path: row for row in cache_result.scalars().all()
    }

    def _scan(
        root: Path, cache: dict[str, EbookMetadataCache]
    ) -> list[dict]:  # type: ignore[type-arg]
        results = []
        for file in root.rglob("*"):
            if file.suffix.lower() not in _EBOOK_EXTENSIONS:
                continue
            try:
                stat = file.stat()
            except OSError:
                logger.debug("Cannot stat %s, skipping", file)
                continue
            path_rel = file.relative_to(root).as_posix()
            cached = cache.get(path_rel)
            if cached and cached.file_mtime == stat.st_mtime and cached.file_size == stat.st_size:
                title, author = cached.title, cached.author
                needs_update = False
            else:
                ext = file.suffix.lower()
                if ext == ".epub":
                    title, author = _extract_epub_metadata(file)
                elif ext == ".pdf":
                    title, author = _extract_pdf_metadata(file)
                else:
                    title, author = None, None
                needs_update = True
            results.append(
                {
                    "path_rel": path_rel,
                    "filename": file.name,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "title": title,
                    "author": author,
                    "needs_update": needs_update,
                }
            )
        return results

    scanned = await asyncio.to_thread(_scan, root, cache_map)

    scanned_paths = {item["path_rel"] for item in scanned}
    stale_paths = set(cache_map.keys()) - scanned_paths
    if stale_paths:
        await session.execute(
            delete(EbookMetadataCache).where(EbookMetadataCache.path.in_(stale_paths))
        )

    for item in scanned:
        if not item["needs_update"]:
            continue
        cached = cache_map.get(item["path_rel"])
        if cached is None:
            session.add(
                EbookMetadataCache(
                    path=item["path_rel"],
                    title=item["title"],
                    author=item["author"],
                    file_mtime=item["mtime"],
                    file_size=item["size"],
                )
            )
        else:
            cached.title = item["title"]
            cached.author = item["author"]
            cached.file_mtime = item["mtime"]
            cached.file_size = item["size"]
    await session.commit()

    return [
        EbookFileSummary(
            path=item["path_rel"],
            filename=item["filename"],
            title=item["title"],
            author=item["author"],
        )
        for item in sorted(scanned, key=lambda x: x["path_rel"])
    ]


@router.get("/mappings", response_model=list[MappingRead])
async def list_mappings(
    user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> list[MappingRead]:
    result = await session.execute(
        select(AbsEbookMapping)
        .where(AbsEbookMapping.user_id == user.id)
        .order_by(AbsEbookMapping.created_at.desc())
    )
    mappings = list(result.scalars().all())

    abs_item_ids = {m.abs_item_id for m in mappings}
    lib_result = await session.execute(
        select(AbsLibraryItem).where(AbsLibraryItem.abs_item_id.in_(abs_item_ids))
    )
    lib_by_id = {li.abs_item_id: li for li in lib_result.scalars().all()}

    kosync_docs = [m.kosync_document for m in mappings if m.kosync_document]
    progress_by_doc: dict[str, float] = {}
    if kosync_docs:
        progress_result = await session.execute(
            select(ReadingProgress)
            .join(KosyncUser, ReadingProgress.kosync_user_id == KosyncUser.id)
            .where(
                KosyncUser.user_id == user.id,
                ReadingProgress.document.in_(kosync_docs),
                ReadingProgress.is_latest == True,
            )
        )
        progress_by_doc = {r.document: r.percentage for r in progress_result.scalars().all()}

    return [
        _mapping_to_schema(m, lib_by_id.get(m.abs_item_id), progress_by_doc.get(m.kosync_document or ""))
        for m in mappings
    ]


@router.post("/mappings", response_model=MappingRead, status_code=201)
async def create_mapping(
    body: MappingCreate,
    user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> MappingRead:
    existing = await session.execute(
        select(AbsEbookMapping).where(
            AbsEbookMapping.user_id == user.id,
            AbsEbookMapping.abs_item_id == body.abs_item_id,
            AbsEbookMapping.ebook_path == body.ebook_path,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Mapping already exists")

    full_path = Path(settings.ebook_local_root) / body.ebook_path
    kosync_document: str | None = None
    try:
        kosync_document = await asyncio.to_thread(partial_md5, full_path)
    except OSError:
        logger.error("Cannot read ebook file: %s", full_path, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not read ebook file")

    mapping = AbsEbookMapping(
        user_id=user.id,
        abs_item_id=body.abs_item_id,
        abs_title=body.abs_title,
        abs_author=body.abs_author,
        ebook_path=body.ebook_path,
        ebook_filename=Path(body.ebook_path).name,
        kosync_document=kosync_document,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)

    if kosync_document is not None:
        kosync_user_result = await session.execute(
            select(KosyncUser).where(KosyncUser.user_id == user.id)
        )
        for kosync_user in kosync_user_result.scalars().all():
            await backfill_progress_titles(
                session,
                kosync_user_id=kosync_user.id,
                document=kosync_document,
                title=body.abs_title,
            )
        await session.commit()

    return _mapping_to_schema(mapping, None)


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    result = await session.execute(
        select(AbsEbookMapping).where(
            AbsEbookMapping.id == mapping_id,
            AbsEbookMapping.user_id == user.id,
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    abs_item_id = mapping.abs_item_id
    await session.delete(mapping)
    await session.commit()
    shutil.rmtree(Path(settings.alignment_cache_dir) / abs_item_id, ignore_errors=True)
    return {"deleted": mapping_id}


@router.post("/mappings/{mapping_id}/sync", response_model=MappingRead, status_code=202)
async def sync_mapping(
    mapping_id: int,
    user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> MappingRead:
    result = await session.execute(
        select(AbsEbookMapping).where(
            AbsEbookMapping.id == mapping_id,
            AbsEbookMapping.user_id == user.id,
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")

    any_active = await session.execute(
        select(AlignmentJob).where(AlignmentJob.status.in_(ACTIVE_STATUSES)).limit(1)
    )
    if any_active.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Another sync is already running")

    job = AlignmentJob(abs_item_id=mapping.abs_item_id, status="pending", progress=0, ebook_path=mapping.ebook_path)
    session.add(job)
    await session.flush()
    mapping.alignment_job_id = job.id
    await session.commit()
    await session.refresh(mapping)

    lib_result = await session.execute(
        select(AbsLibraryItem).where(AbsLibraryItem.abs_item_id == mapping.abs_item_id)
    )
    lib_item = lib_result.scalar_one_or_none()

    asyncio.create_task(run_alignment_job(job.id))
    return _mapping_to_schema(mapping, lib_item)
