import logging
import re
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup, Tag
from ebooklib import epub
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.config import settings
from earmark.models import AbsEbookMapping

logger = logging.getLogger(__name__)

_DOCFRAGMENT_RE = re.compile(r"^/body/DocFragment\[(\d+)\](.*)")
_TEXT_NODE_SUFFIX_RE = re.compile(r"/text\(\)(?:\[\d+\])?(?:\.\d+)?$")
_SEGMENT_RE = re.compile(r"^(\w+)(?:\[(\d+)\])?$")


def _parse_path_steps(path: str) -> list[tuple[str, int]] | None:
    steps = []
    for seg in path.split("/"):
        if not seg:
            continue
        m = _SEGMENT_RE.match(seg)
        if not m:
            return None
        steps.append((m.group(1), int(m.group(2)) if m.group(2) else 1))
    return steps


def validate_progress_position(epub_path: Path, position: str) -> bool:
    """Return True if position XPath refers to a real element in the EPUB.

    Synchronous — run via asyncio.to_thread.
    """
    m = _DOCFRAGMENT_RE.match(position)
    if not m:
        # KOReader always emits DocFragment paths; any other format is malformed
        return False

    spine_pos = int(m.group(1))  # 1-based
    rel_path = m.group(2)

    try:
        book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        spine_items = [item_id for item_id, _ in book.spine]

        if spine_pos < 1 or spine_pos > len(spine_items):
            return False

        item = book.get_item_with_id(spine_items[spine_pos - 1])
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            return False

        clean_path = _TEXT_NODE_SUFFIX_RE.sub("", rel_path)
        steps = _parse_path_steps(clean_path)

        if steps is None:
            return False
        if not steps:
            return True

        soup = BeautifulSoup(item.get_content(), "html.parser")
        node: Tag | None = soup.body
        if node is None:
            return False

        for tag, idx in steps:
            if tag == "body":
                continue  # already at body
            children = [c for c in node.children if isinstance(c, Tag) and c.name == tag]
            if idx < 1 or idx > len(children):
                return False
            node = children[idx - 1]

        return True

    except Exception:
        logger.warning("EPUB position validation failed for %s", epub_path, exc_info=True)
        return True  # fail open on parse errors


async def find_epub_for_document(
    session: AsyncSession, user_id: int | None, document: str
) -> Path | None:
    """Return the local EPUB path for a document hash, or None if not found."""
    if user_id is None:
        return None

    result = await session.execute(
        select(AbsEbookMapping).where(
            AbsEbookMapping.user_id == user_id,
            AbsEbookMapping.kosync_document == document,
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        return None

    job = mapping.alignment_job
    if job is not None and job.ebook_cache_path:
        cached = Path(job.ebook_cache_path)
        if cached.suffix == ".epub" and cached.exists():
            return cached

    local = Path(settings.ebook_local_root) / mapping.ebook_path
    if local.suffix == ".epub" and local.exists():
        return local

    return None
