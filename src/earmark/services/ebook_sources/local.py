import asyncio
import logging
import shutil
from pathlib import Path

from earmark.config import settings
from earmark.services.ebook_sources.base import EbookCandidate, normalize

logger = logging.getLogger(__name__)


class LocalEbookSource:
    """Resolves ebooks against the configured local root directory."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else Path(settings.ebook_local_root)

    async def search(self, title: str, author: str | None) -> list[EbookCandidate]:
        return await asyncio.to_thread(self._search_sync, title, author or "")

    def _search_sync(self, title: str, author: str) -> list[EbookCandidate]:
        norm_title = normalize(title)
        norm_author = normalize(author)
        root = self._root
        if not root.is_dir() or not norm_title:
            return []

        # (priority, path); lower priority is better.
        ranked: list[tuple[int, Path]] = []
        for epub_path in root.rglob("*.epub"):
            name = normalize(epub_path.stem)
            parent = normalize(epub_path.parent.name)
            if name == norm_title:
                priority = 1 if parent == norm_author else 2
                ranked.append((priority, epub_path))
            elif norm_title in normalize(str(epub_path)):
                ranked.append((3, epub_path))

        ranked.sort(key=lambda x: (x[0], str(x[1])))
        return [
            EbookCandidate(
                ref=str(path.relative_to(root)),
                title=path.stem,
                author=author or None,
                format="epub",
            )
            for _priority, path in ranked
        ]

    async def fetch(self, ref: str, dest: Path) -> None:
        src = self._root / ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, src, dest)
