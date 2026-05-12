from httpx import AsyncClient


async def test_healthcheck(client: AsyncClient) -> None:
    response = await client.get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"state": "OK"}
