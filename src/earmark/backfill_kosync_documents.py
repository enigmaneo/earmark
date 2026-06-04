import asyncio
import logging
import tempfile
from pathlib import Path

from sqlalchemy import or_, select

from earmark.database import AsyncSessionLocal
from earmark.models import AbsEbookMapping
from earmark.services.ebook_sources import CalibreOpdsSource
from earmark.services.progress import link_progress_to_mapping
from earmark.utils import partial_md5

logger = logging.getLogger(__name__)


async def backfill() -> None:
    """Fill kosync_document for calibre mappings that never got one.

    Calibre mappings used to be created without a KOReader partial-MD5 (only
    local mappings computed it), so pushed progress could never be linked. This
    downloads each such ebook, computes the hash, stores it, and links any
    matching progress.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AbsEbookMapping).where(
                AbsEbookMapping.ebook_source == "calibre",
                or_(
                    AbsEbookMapping.kosync_document.is_(None),
                    AbsEbookMapping.kosync_document == "",
                ),
            )
        )
        mappings = list(result.scalars().all())

    print(f"Found {len(mappings)} calibre mapping(s) needing a kosync_document.")
    source = CalibreOpdsSource()

    for mapping in mappings:
        if not mapping.ebook_source_ref:
            print(f"  #{mapping.id} {mapping.abs_title!r}: no ebook_source_ref, skipping")
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "ebook.epub"
                await source.fetch(mapping.ebook_source_ref, dest)
                doc = await asyncio.to_thread(partial_md5, dest)
        except Exception:
            logger.exception("Failed to hash mapping #%d (%s)", mapping.id, mapping.abs_title)
            continue

        async with AsyncSessionLocal() as session:
            fresh = await session.get(AbsEbookMapping, mapping.id)
            if fresh is None or fresh.kosync_document:
                continue
            fresh.kosync_document = doc
            await session.commit()
            await link_progress_to_mapping(session, fresh)
            await session.commit()
        print(f"  #{mapping.id} {mapping.abs_title!r}: kosync_document={doc}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill())
    print("Done.")


if __name__ == "__main__":
    main()
