from pathlib import Path

import httpx

from earmark.config import settings

_DOWNLOAD_TIMEOUT = httpx.Timeout(10.0, read=300.0)


class AudiobookshelfClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.audiobookshelf_url,
            headers={"Authorization": f"Bearer {settings.audiobookshelf_api_key}"},
            timeout=10.0,
        )

    async def get_progress(self, item_id: str) -> dict:  # type: ignore[type-arg]
        # TODO: implement
        raise NotImplementedError

    async def get_item(self, item_id: str) -> dict:  # type: ignore[type-arg]
        response = await self._client.get(f"/api/items/{item_id}", params={"expanded": "1"})
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def download_audio_file(self, item_id: str, filename: str, dest_path: Path) -> None:
        url = f"/api/items/{item_id}/file/{filename}"
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

    async def close(self) -> None:
        await self._client.aclose()
