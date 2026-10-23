from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from async_server import KEEPER_KEY, create_app
from errors import UpstreamUnavailable
from genome import MISSING_TOKEN_SENTINEL


class FakeTokenSource:
    async def get_token_data(self, token_id: int) -> int:
        if token_id == 0:
            return 1 << 35
        if token_id == 1:
            return MISSING_TOKEN_SENTINEL
        raise UpstreamUnavailable("simulated upstream outage")


class BurnAfterFirstReadSource:
    def __init__(self) -> None:
        self.calls = 0

    async def get_token_data(self, token_id: int) -> int:
        del token_id
        self.calls += 1
        return (1 << 35) if self.calls == 1 else MISSING_TOKEN_SENTINEL


async def test_http_statuses_and_generated_artifacts(miniature_config) -> None:
    app = await create_app(miniature_config, token_source=FakeTokenSource())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/health")
        assert response.status == 200
        assert (await response.json())["chain_reads_enabled"] is False

        response = await client.get("/token/not-a-number")
        assert response.status == 400
        response = await client.get("/token/999")
        assert response.status == 400

        response = await client.get("/token/1")
        assert response.status == 404
        response = await client.get("/image/1")
        assert response.status == 404

        response = await client.get("/token/2")
        assert response.status == 503

        response = await client.get("/token/0")
        assert response.status == 200
        metadata = await response.json()
        assert metadata["name"] == "Alvara #0"
        assert metadata["image"] == "http://127.0.0.1:8080/image/0"

        response = await client.get("/image/0")
        assert response.status == 200
        assert response.content_type == "image/png"
        response = await client.get("/external/0")
        assert response.status == 200
        assert response.content_type == "image/png"

        # A partial cache is regenerated as one two-resolution bundle.
        keeper = app[KEEPER_KEY]
        keeper.path_to_image(0).unlink()
        response = await client.get("/token/0")
        assert response.status == 200
        assert keeper.path_to_image(0).is_file()
    finally:
        await client.close()


async def test_cached_metadata_does_not_hide_a_burned_token(miniature_config) -> None:
    app = await create_app(
        miniature_config,
        token_source=BurnAfterFirstReadSource(),
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        assert (await client.get("/token/0")).status == 200
        assert (await client.get("/token/0")).status == 404
        assert (await client.get("/image/0")).status == 404
        assert (await client.get("/external/0")).status == 404
    finally:
        await client.close()
