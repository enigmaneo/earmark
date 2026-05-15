import asyncio
import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import ffmpeg
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from earmark.config import settings
from earmark.database import AsyncSessionLocal
from earmark.models import AbsLibraryItem, AlignmentJob
from earmark.services.audiobookshelf import AudiobookshelfClient

logger = logging.getLogger(__name__)

# ── synchronous helpers (run via asyncio.to_thread) ────────────────────────────

_BLOCK_TAGS: list[str] = ["p", "h1", "h2", "h3", "h4", "h5", "h6"]

_FRONT_MATTER_TITLES: frozenset[str] = frozenset({
    "cover", "title page", "dedication", "contents", "copyright",
    "preface", "foreword", "acknowledgments", "about the author",
    "half title", "halftitle",
})


def _find_first_chapter_spine_pos(book: object, spine_items: list[str]) -> int:
    """Return 1-based spine position of the first non-front-matter TOC entry."""
    def _scan(items: list) -> int | None:  # type: ignore[type-arg]
        for item in items:
            if isinstance(item, tuple):
                _, children = item
                result = _scan(children)
                if result is not None:
                    return result
            elif hasattr(item, "href"):
                if item.title.strip().lower() not in _FRONT_MATTER_TITLES:
                    href_file = item.href.split("#")[0]
                    for pos, item_id in enumerate(spine_items, start=1):
                        spine_item = book.get_item_with_id(item_id)  # type: ignore[union-attr]
                        if spine_item and (
                            href_file.endswith(spine_item.file_name)
                            or spine_item.file_name.endswith(href_file)
                        ):
                            return pos
        return None

    return _scan(book.toc) or 1  # type: ignore[union-attr]


def _parse_epub_sync(epub_path: Path) -> tuple[list[str], dict[str, dict[str, str]], int]:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(epub_path))
    spine_items = [item_id for item_id, _ in book.spine]

    paragraphs: list[str] = []
    index: dict[str, dict[str, str]] = {}
    seq = 0

    first_chapter_spine_pos = _find_first_chapter_spine_pos(book, spine_items)

    for spine_pos, item_id in enumerate(spine_items, start=1):
        if spine_pos < first_chapter_spine_pos:
            continue
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Skip table-of-contents pages — they're not narrated in audiobooks.
        if soup.find(attrs={"role": "doc-toc"}):
            continue
        tag_counters: dict[str, int] = {}
        for element in soup.find_all(_BLOCK_TAGS):
            text = element.get_text(separator=" ").strip()
            if not text:
                continue
            tag_name = element.name
            tag_counters[tag_name] = tag_counters.get(tag_name, 0) + 1
            para_id = f"para_{seq:03d}"
            ebook_pos = f"/body/DocFragment[{spine_pos}]/body/{tag_name}[{tag_counters[tag_name]}]"
            index[para_id] = {"text": text, "ebook_pos": ebook_pos}
            paragraphs.append(text)
            seq += 1

    return paragraphs, index, first_chapter_spine_pos


def _ffmpeg_trim_sync(input_path: Path, output_path: Path, start: float) -> None:
    (
        ffmpeg.input(str(input_path), ss=start)
        .output(str(output_path), ar=16000, ac=1, acodec="pcm_s16le")
        .overwrite_output()
        .run(quiet=True)
    )


def _ffmpeg_concat_sync(audio_files: list[Path], output_path: Path) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        concat_list = Path(f.name)
        for p in audio_files:
            f.write(f"file '{p.absolute()}'\n")

    try:
        (
            ffmpeg.input(str(concat_list), format="concat", safe=0)
            .output(str(output_path), ar=16000, ac=1, acodec="pcm_s16le")
            .overwrite_output()
            .run(quiet=True)
        )
    finally:
        concat_list.unlink(missing_ok=True)


def _run_aeneas_sync(
    audio_path: Path, paragraphs_path: Path, raw_output_path: Path
) -> list[dict[str, str]]:
    from aeneas.executetask import ExecuteTask
    from aeneas.task import Task

    config_str = (
        "task_language=eng"
        "|is_text_type=plain"
        "|os_task_file_format=json"
        "|task_adjust_boundary_algorithm=rate"
        "|task_adjust_boundary_rate_value=21"
    )
    task = Task(config_string=config_str)
    task.audio_file_path_absolute = str(audio_path)
    task.text_file_path_absolute = str(paragraphs_path)
    task.sync_map_file_path_absolute = str(raw_output_path)

    ExecuteTask(task).execute()
    task.output_sync_map_file()

    with raw_output_path.open() as f:
        data = json.load(f)
    return data["fragments"]  # type: ignore[no-any-return]


def _rescale_to_chapters(
    sync_map: list[dict],  # type: ignore[type-arg]
    chapters: list[dict],  # type: ignore[type-arg]
    first_chapter_spine_pos: int,
) -> None:
    """Linearly rescale aeneas timestamps within each EPUB chapter to match ABS chapter boundaries.

    Assumes ABS chapters[1], chapters[2], ... correspond to EPUB DocFragment[first_chapter_spine_pos],
    DocFragment[first_chapter_spine_pos+1], etc. (one ABS chapter per spine item).
    Entries whose spine position doesn't map to a valid chapter index are left unchanged.
    """
    import re

    if len(chapters) < 2:
        return

    logger.info(
        "Chapter rescaling: %d ABS chapters, first_chapter_spine_pos=%d",
        len(chapters),
        first_chapter_spine_pos,
    )

    def _spine_pos(ebook_pos: str) -> int | None:
        m = re.match(r"/body/DocFragment\[(\d+)\]/", ebook_pos)
        return int(m.group(1)) if m else None

    # Group sync_map entry indices by spine position
    groups: dict[int, list[int]] = {}
    for i, entry in enumerate(sync_map):
        sp = _spine_pos(entry["ebook_pos"])
        if sp is not None:
            groups.setdefault(sp, []).append(i)

    for spine_pos in sorted(groups.keys()):
        indices = groups[spine_pos]
        ch_idx = spine_pos - first_chapter_spine_pos + 1
        if ch_idx < 1 or ch_idx >= len(chapters):
            continue

        abs_ch_start = float(chapters[ch_idx]["start"])
        abs_ch_end = (
            float(chapters[ch_idx + 1]["start"])
            if ch_idx + 1 < len(chapters)
            else sync_map[indices[-1]]["audio_end"]
        )

        aeneas_ch_start = sync_map[indices[0]]["audio_start"]
        aeneas_ch_end = sync_map[indices[-1]]["audio_end"]
        aeneas_duration = aeneas_ch_end - aeneas_ch_start
        abs_duration = abs_ch_end - abs_ch_start

        if aeneas_duration <= 0 or abs_duration <= 0:
            continue

        scale = abs_duration / aeneas_duration
        logger.debug(
            "DocFragment[%d] → chapter %d: aeneas [%.2f, %.2f] → abs [%.2f, %.2f] (scale=%.3f)",
            spine_pos, ch_idx, aeneas_ch_start, aeneas_ch_end, abs_ch_start, abs_ch_end, scale,
        )

        for i in indices:
            e = sync_map[i]
            e["audio_start"] = abs_ch_start + (e["audio_start"] - aeneas_ch_start) * scale
            e["audio_end"] = abs_ch_start + (e["audio_end"] - aeneas_ch_start) * scale


# ── pipeline class ──────────────────────────────────────────────────────────────


class AlignmentPipeline:
    def __init__(self, job: AlignmentJob, session: AsyncSession) -> None:
        self.job = job
        self.session = session
        self._abs = AudiobookshelfClient()

    async def run(self) -> None:
        try:
            item_metadata = await self._fetch_abs_metadata()
            cache_dir = self._cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)

            chapters = item_metadata.get("media", {}).get("chapters", [])
            chapter_start = float(chapters[1]["start"]) if len(chapters) >= 2 else 0.0

            audio_dir = await self._download_audio_files(cache_dir, item_metadata)
            ebook_path = await self._download_ebook(cache_dir, item_metadata)
            paragraphs, index, first_chapter_spine_pos = await self._parse_epub(ebook_path)
            audio_path = await self._prepare_audio(audio_dir, chapter_start)
            fragments = await self._run_aeneas(cache_dir, audio_path, paragraphs)
            await self._assemble_sync_map(
                cache_dir, fragments, index, chapter_start, chapters, first_chapter_spine_pos
            )
        except Exception as exc:
            logger.exception("Alignment job %d failed", self.job.id)
            await self._fail(str(exc))
        finally:
            await self._abs.close()

    # ── stages ─────────────────────────────────────────────────────────────────

    async def _fetch_abs_metadata(self) -> dict:  # type: ignore[type-arg]
        await self._update_status("fetching_audio", progress=5)
        item = await self._abs.get_item(self.job.abs_item_id)

        media = item.get("media", {})
        audio_files = media.get("audioFiles", [])
        ebook_file = media.get("ebookFile")
        metadata = media.get("metadata", {})
        abs_updated_at_ms: int | None = item.get("updatedAt")
        abs_updated_at = (
            datetime.fromtimestamp(abs_updated_at_ms / 1000, tz=UTC)
            if abs_updated_at_ms
            else None
        )

        # Upsert AbsLibraryItem
        result = await self.session.execute(
            select(AbsLibraryItem).where(
                AbsLibraryItem.abs_item_id == self.job.abs_item_id
            )
        )
        lib_item = result.scalar_one_or_none()
        if lib_item is None:
            lib_item = AbsLibraryItem(abs_item_id=self.job.abs_item_id)
            self.session.add(lib_item)

        lib_item.library_id = item.get("libraryId", "")
        lib_item.title = metadata.get("title", "")
        lib_item.author = metadata.get("authorName")
        lib_item.ebook_filename = ebook_file["filename"] if ebook_file else None
        lib_item.ebook_format = (
            ebook_file["ext"].lstrip(".").lower() if ebook_file else None
        )
        lib_item.audio_file_count = len(audio_files)
        lib_item.total_duration_seconds = sum(
            f.get("duration", 0) for f in audio_files
        )
        lib_item.abs_updated_at = abs_updated_at
        lib_item.raw_metadata = json.dumps(item)
        await self.session.commit()

        # Invalidate stale cache
        sentinel = self._cache_dir() / ".abs_updated_at"
        if sentinel.exists() and abs_updated_at:
            cached_ts = sentinel.read_text().strip()
            if cached_ts != abs_updated_at.isoformat():
                shutil.rmtree(self._cache_dir(), ignore_errors=True)
                logger.info("Cache invalidated for %s", self.job.abs_item_id)

        return item  # type: ignore[return-value]

    async def _download_audio_files(
        self, cache_dir: Path, item_metadata: dict  # type: ignore[type-arg]
    ) -> Path:
        audio_dir = cache_dir / "audio"
        audio_files = item_metadata.get("media", {}).get("audioFiles", [])
        sorted_files = sorted(audio_files, key=lambda f: f.get("index", 0))
        width = max(3, len(str(len(sorted_files))))

        for i, af in enumerate(sorted_files):
            ino = af.get("ino", "")
            filename = af.get("metadata", {}).get("filename") or af.get("filename", "")
            dest = audio_dir / f"{i:0{width}}_{filename}"
            if dest.exists():
                continue
            for attempt in range(3):
                try:
                    await self._abs.download_audio_file(
                        self.job.abs_item_id, ino, dest
                    )
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2**attempt)

        await self._update_status("fetching_audio", progress=20, audio_cache_dir=str(audio_dir))

        # Write cache sentinel
        abs_updated_at = item_metadata.get("updatedAt")
        if abs_updated_at:
            sentinel = cache_dir / ".abs_updated_at"
            dt = datetime.fromtimestamp(abs_updated_at / 1000, tz=UTC)
            sentinel.write_text(dt.isoformat())

        return audio_dir

    async def _download_ebook(
        self, cache_dir: Path, item_metadata: dict  # type: ignore[type-arg]
    ) -> Path:
        await self._update_status("fetching_ebook", progress=30)
        ebook_path = cache_dir / "ebook.epub"

        # CLI override: ebook_cache_path already set, copy into standard location
        if self.job.ebook_cache_path and self.job.ebook_cache_path != str(ebook_path):
            src = Path(self.job.ebook_cache_path)
            if not ebook_path.exists():
                shutil.copy2(src, ebook_path)
            await self._update_status("fetching_ebook", progress=40, ebook_cache_path=str(ebook_path))
            return ebook_path

        if ebook_path.exists():
            await self._update_status("fetching_ebook", progress=40, ebook_cache_path=str(ebook_path))
            return ebook_path

        source = settings.ebook_source
        if source == "abs":
            await self._download_ebook_from_abs(ebook_path, item_metadata)
        elif source == "cwa":
            await self._download_ebook_from_cwa(ebook_path, item_metadata)
        elif source == "local":
            await self._download_ebook_from_local(ebook_path, item_metadata)
        else:
            raise ValueError(f"Unknown ebook_source: {source!r}")

        await self._update_status("fetching_ebook", progress=40, ebook_cache_path=str(ebook_path))
        return ebook_path

    async def _download_ebook_from_abs(
        self, dest: Path, item_metadata: dict  # type: ignore[type-arg]
    ) -> None:
        ebook_file = item_metadata.get("media", {}).get("ebookFile")
        if not ebook_file:
            raise ValueError(
                f"No ebook file on ABS item {self.job.abs_item_id}"
            )
        for attempt in range(3):
            try:
                await self._abs.download_ebook(self.job.abs_item_id, dest)
                return
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)

    async def _download_ebook_from_cwa(
        self, dest: Path, item_metadata: dict  # type: ignore[type-arg]
    ) -> None:
        import base64
        import re
        import unicodedata

        media = item_metadata.get("media", {})
        title = media.get("metadata", {}).get("title", "")
        author = media.get("metadata", {}).get("authorName", "")

        def normalize(s: str) -> str:
            s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
            return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

        norm_title = normalize(title)
        norm_author = normalize(author)

        credentials = base64.b64encode(
            f"{settings.cwa_username}:{settings.cwa_password}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        async with httpx.AsyncClient(base_url=settings.cwa_url) as client:
            resp = await client.get(
                f"/opds/search/{norm_title}", headers=headers, follow_redirects=True
            )
            resp.raise_for_status()

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "xml")
        candidates = []
        for entry in soup.find_all("entry"):
            entry_title = entry.find("title")
            entry_title_text = entry_title.get_text() if entry_title else ""
            if normalize(entry_title_text) != norm_title:
                continue
            author_tag = entry.find("author")
            if author_tag:
                name_tag = author_tag.find("name")
                entry_author = name_tag.get_text() if name_tag else ""
                if normalize(entry_author) != norm_author:
                    continue
            link = entry.find("link", attrs={"type": "application/epub+zip"})
            if link:
                candidates.append(link.get("href", ""))

        if len(candidates) == 0:
            raise ValueError(
                f"CWA: no EPUB match for title={norm_title!r} author={norm_author!r}"
            )
        if len(candidates) > 1:
            raise ValueError(
                f"CWA: ambiguous match for {norm_title!r} — {len(candidates)} candidates"
            )

        href = candidates[0]
        async with httpx.AsyncClient(
            base_url=settings.cwa_url, timeout=httpx.Timeout(10.0, read=300.0)
        ) as client:
            async with client.stream(
                "GET", href, headers=headers, follow_redirects=True
            ) as resp:
                resp.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)

    async def _download_ebook_from_local(
        self, dest: Path, item_metadata: dict  # type: ignore[type-arg]
    ) -> None:
        import re
        import unicodedata

        media = item_metadata.get("media", {})
        title = media.get("metadata", {}).get("title", "")
        author = media.get("metadata", {}).get("authorName", "")

        def normalize(s: str) -> str:
            s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
            return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

        norm_title = normalize(title)
        norm_author = normalize(author)
        root = Path(settings.ebook_local_root)

        candidates: list[tuple[int, Path]] = []
        for epub_path in root.rglob("*.epub"):
            name = normalize(epub_path.stem)
            parent = normalize(epub_path.parent.name)
            if name == norm_title:
                priority = 1 if parent == norm_author else 2
                candidates.append((priority, epub_path))
            elif norm_title in normalize(str(epub_path)):
                candidates.append((3, epub_path))

        if not candidates:
            raise ValueError(
                f"No EPUB found in {root} for title={norm_title!r} author={norm_author!r}"
            )

        candidates.sort(key=lambda x: x[0])
        best_priority, best_path = candidates[0]
        if best_priority == 3:
            logger.warning(
                "Local EPUB match is fuzzy: %s (title=%r)", best_path, norm_title
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best_path, dest)

    async def _parse_epub(self, epub_path: Path) -> tuple[list[str], dict[str, dict[str, str]], int]:
        await self._update_status("parsing_epub", progress=50)
        paragraphs, index, first_chapter_spine_pos = await asyncio.to_thread(_parse_epub_sync, epub_path)
        await self._update_status("parsing_epub", progress=60, paragraph_count=len(paragraphs))
        return paragraphs, index, first_chapter_spine_pos

    async def _prepare_audio(self, audio_dir: Path, trim_start: float = 0.0) -> Path:
        audio_files = sorted(audio_dir.glob("*"))
        audio_files = [f for f in audio_files if f.is_file()]
        concat_path = audio_dir.parent / "concatenated.wav"
        trimmed_path = audio_dir.parent / "trimmed.wav"

        if len(audio_files) == 1 and audio_files[0].suffix.lower() in (".mp3", ".m4b", ".m4a"):
            src = audio_files[0]
        else:
            try:
                await asyncio.to_thread(_ffmpeg_concat_sync, audio_files, concat_path)
            except Exception as exc:
                logger.warning("Strategy A (concat) failed: %s — falling back to per-file", exc)
                raise
            src = concat_path

        if trim_start > 0.0:
            await asyncio.to_thread(_ffmpeg_trim_sync, src, trimmed_path, trim_start)
            return trimmed_path

        return src

    async def _run_aeneas(
        self,
        cache_dir: Path,
        audio_path: Path,
        paragraphs: list[str],
    ) -> list[dict[str, str]]:
        await self._update_status("aligning", progress=65)

        paragraphs_path = cache_dir / "paragraphs.txt"
        paragraphs_path.write_text("\n".join(paragraphs) + "\n", encoding="utf-8")

        raw_output_path = cache_dir / "aeneas_raw.json"
        fragments = await asyncio.to_thread(
            _run_aeneas_sync, audio_path, paragraphs_path, raw_output_path
        )

        await self._update_status("aligning", progress=85, fragment_count=len(fragments))
        return fragments

    async def _assemble_sync_map(
        self,
        cache_dir: Path,
        fragments: list[dict[str, str]],
        index: dict[str, dict[str, str]],
        chapter_start: float,
        chapters: list[dict],  # type: ignore[type-arg]
        first_chapter_spine_pos: int,
    ) -> None:
        await self._update_status("assembling", progress=90)

        para_count = len(index)
        frag_count = len(fragments)
        if para_count != frag_count:
            logger.warning(
                "Fragment/paragraph mismatch: %d fragments, %d paragraphs — "
                "aligning up to min(%d, %d)",
                frag_count,
                para_count,
                frag_count,
                para_count,
            )

        sync_map = []
        count = min(para_count, frag_count)
        para_ids = sorted(index.keys())[:count]

        for i, para_id in enumerate(para_ids):
            fragment = fragments[i]
            entry = index[para_id]
            sync_map.append(
                {
                    "id": para_id,
                    "audio_start": float(fragment["begin"]) + chapter_start,
                    "audio_end": float(fragment["end"]) + chapter_start,
                    "ebook_pos": entry["ebook_pos"],
                    "text_snippet": entry["text"],
                }
            )

        if chapter_start > 0.0:
            logger.info("Applied chapter start offset %.2fs to all sync map entries", chapter_start)

        _rescale_to_chapters(sync_map, chapters, first_chapter_spine_pos)

        sync_map_path = cache_dir / "sync_map.json"
        sync_map_path.write_text(
            json.dumps(sync_map, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Clean up ephemeral files
        for ephemeral in ["concatenated.wav", "trimmed.wav", "paragraphs.txt", "aeneas_raw.json"]:
            (cache_dir / ephemeral).unlink(missing_ok=True)

        await self._update_status(
            "complete",
            progress=100,
            sync_map_path=str(sync_map_path),
            fragment_count=frag_count,
            paragraph_count=para_count,
            audio_offset_seconds=chapter_start if chapter_start > 0.0 else None,
            completed_at=datetime.now(tz=UTC),
        )

    # ── helpers ─────────────────────────────────────────────────────────────────

    def _cache_dir(self) -> Path:
        return Path(settings.alignment_cache_dir) / self.job.abs_item_id

    async def _update_status(self, status: str, progress: int | None = None, **kwargs: object) -> None:
        self.job.status = status
        if progress is not None:
            self.job.progress = progress
        for k, v in kwargs.items():
            setattr(self.job, k, v)
        await self.session.commit()

    async def _fail(self, message: str) -> None:
        self.job.status = "failed"
        self.job.error_message = message
        await self.session.commit()


# ── module-level entry point ────────────────────────────────────────────────────


async def run_alignment_job(
    job_id: int,
    session_factory: async_sessionmaker | None = None,  # type: ignore[type-arg]
) -> None:
    """Entry point for the alignment pipeline. Opens its own session.

    The optional session_factory is used in tests to inject the test DB session.
    In production, the module-level AsyncSessionLocal is used.
    """
    factory = session_factory if session_factory is not None else AsyncSessionLocal
    async with factory() as session:
        result = await session.execute(
            select(AlignmentJob).where(AlignmentJob.id == job_id)
        )
        job = result.scalar_one()
        await AlignmentPipeline(job, session).run()
