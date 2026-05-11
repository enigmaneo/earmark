import httpx

from earmark.config import settings


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

    async def close(self) -> None:
        await self._client.aclose()
