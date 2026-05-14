import asyncio
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.config import settings
from earmark.database import get_session
from earmark.earmark_auth import get_current_earmark_user
from earmark.models import AbsEbookMapping, AbsLibraryItem, EbookMetadataCache, User
from earmark.schemas import AbsItemSummary, EbookFileSummary, MappingCreate, MappingRead
from earmark.services.audiobookshelf import AudiobookshelfClient

router = APIRouter(prefix="/web", tags=["mappings"])

_EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw3"}


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
            pass

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
) -> list[AbsEbookMapping]:
    result = await session.execute(
        select(AbsEbookMapping)
        .where(AbsEbookMapping.user_id == user.id)
        .order_by(AbsEbookMapping.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/mappings", response_model=MappingRead, status_code=201)
async def create_mapping(
    body: MappingCreate,
    user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> AbsEbookMapping:
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
        content = await asyncio.to_thread(full_path.read_bytes)
        kosync_document = hashlib.md5(content).hexdigest()
    except OSError:
        pass

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
    return mapping


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
    await session.delete(mapping)
    await session.commit()
    return {"deleted": mapping_id}
