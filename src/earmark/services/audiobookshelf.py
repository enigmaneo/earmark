import logging
from pathlib import Path

import httpx

from earmark.config import settings

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = httpx.Timeout(10.0, read=300.0)


class AudiobookshelfClient:
    def __init__(self) -> None:
        logger.debug("AudiobookshelfClient connecting to %s", settings.audiobookshelf_url)
        self._client = httpx.AsyncClient(
            base_url=settings.audiobookshelf_url,
            headers={"Authorization": f"Bearer {settings.audiobookshelf_api_key}"},
            timeout=10.0,
        )

    async def get_progress(self, item_id: str) -> dict | None:  # type: ignore[type-arg]
        response = await self._client.get(f"/api/me/progress/{item_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def update_progress(
        self, item_id: str, current_time: float, duration: float, progress: float
    ) -> None:
        response = await self._client.patch(
            f"/api/me/progress/{item_id}",
            json={"currentTime": current_time, "duration": duration, "progress": progress},
        )
        response.raise_for_status()

    async def get_item(self, item_id: str) -> dict:  # type: ignore[type-arg]
        response = await self._client.get(f"/api/items/{item_id}", params={"expanded": "1"})
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def download_audio_file(self, item_id: str, file_id: str, dest_path: Path) -> None:
        url = f"/api/items/{item_id}/file/{file_id}"
        async with self._client.stream("GET", url, timeout=_DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    async def download_ebook(self, item_id: str, dest_path: Path) -> None:
        url = f"/api/items/{item_id}/ebook"
        async with self._client.stream("GET", url, timeout=_DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    async def list_libraries(self) -> list[dict]:  # type: ignore[type-arg]
        response = await self._client.get("/api/libraries")
        response.raise_for_status()
        return response.json().get("libraries", [])  # type: ignore[no-any-return]

    async def list_library_items(self, library_id: str) -> list[dict]:  # type: ignore[type-arg]
        response = await self._client.get(
            f"/api/libraries/{library_id}/items", params={"limit": "0"}
        )
        response.raise_for_status()
        return response.json().get("results", [])  # type: ignore[no-any-return]

    async def close(self) -> None:
        await self._client.aclose()
