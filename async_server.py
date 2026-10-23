"""aiohttp application factory with no import-time network or filesystem side effects."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from artifacts_keeper import ArtifactsKeeper
from cache_identity import CACHE_FORMAT_VERSION, cache_namespace
from collection_settings import CollectionSettings, load_collection_settings
from config import AppConfig
from errors import (
    ArtifactGenerationError,
    ArtifactNotFound,
    InvalidGenome,
    InvalidTokenId,
    StatePersistenceError,
    TokenNotFound,
    UpstreamUnavailable,
)
from meta_generator import MetaGenerator
from smart_client import (
    DisabledTokenDataSource,
    TokenDataSource,
    Web3TokenDataSource,
)
from token_state import TokenState

LOGGER = logging.getLogger(__name__)
CONFIG_KEY: web.AppKey[AppConfig] = web.AppKey("config", AppConfig)
SETTINGS_KEY: web.AppKey[CollectionSettings] = web.AppKey("settings", CollectionSettings)
KEEPER_KEY: web.AppKey[ArtifactsKeeper] = web.AppKey("keeper", ArtifactsKeeper)
GENERATOR_KEY: web.AppKey[MetaGenerator] = web.AppKey("generator", MetaGenerator)
SOURCE_KEY: web.AppKey[Any] = web.AppKey("source", object)
CACHE_ROOT_KEY: web.AppKey[Any] = web.AppKey("cache_root", object)


def _json_error(status: int, code: str) -> web.Response:
    return web.json_response({"error": code}, status=status)


@web.middleware
async def error_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    try:
        return await handler(request)
    except InvalidTokenId:
        return _json_error(400, "invalid_token_id")
    except (TokenNotFound, ArtifactNotFound):
        return _json_error(404, "token_or_artifact_not_found")
    except (UpstreamUnavailable, InvalidGenome):
        return _json_error(503, "token_data_unavailable")
    except (ArtifactGenerationError, StatePersistenceError):
        LOGGER.exception("local artifact pipeline failed")
        return _json_error(503, "artifact_pipeline_unavailable")
    except web.HTTPException:
        raise
    except Exception:
        LOGGER.exception("unexpected request failure")
        return _json_error(500, "internal_error")


def _token_id(request: web.Request) -> int:
    raw = request.match_info["id"]
    settings = request.app[SETTINGS_KEY]
    max_digits = len(str(settings.collection_size - 1))
    if not raw or not raw.isascii() or not raw.isdecimal() or len(raw) > max_digits:
        raise InvalidTokenId("token ID must be bounded ASCII decimal digits")
    token_id = int(raw)
    if not 0 <= token_id < settings.collection_size:
        raise InvalidTokenId("token ID is outside the collection range")
    return token_id


async def token_meta(request: web.Request) -> web.Response:
    content = await request.app[GENERATOR_KEY].meta(_token_id(request))
    return web.json_response(content)


async def image(request: web.Request) -> web.Response:
    token_id = _token_id(request)
    await request.app[GENERATOR_KEY].meta(token_id)
    return web.FileResponse(
        request.app[KEEPER_KEY].path_to_image(token_id),
        headers={"Cache-Control": "no-store", "Content-Type": "image/png"},
    )


async def external(request: web.Request) -> web.Response:
    token_id = _token_id(request)
    await request.app[GENERATOR_KEY].meta(token_id)
    return web.FileResponse(
        request.app[KEEPER_KEY].path_to_external(token_id),
        headers={"Cache-Control": "no-store", "Content-Type": "image/png"},
    )


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "chain_reads_enabled": request.app[CONFIG_KEY].chain_enabled,
        }
    )


async def _close_source(app: web.Application) -> None:
    close = getattr(app[SOURCE_KEY], "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def create_app(
    config: AppConfig | None = None,
    *,
    token_source: TokenDataSource | None = None,
) -> web.Application:
    selected_config = config or AppConfig.from_env()
    selected_config.validate()
    settings = load_collection_settings(selected_config.settings_path)
    namespace = cache_namespace(selected_config, settings)
    cache_root = selected_config.artifacts_dir / f"cache-v{CACHE_FORMAT_VERSION}" / namespace
    keeper = ArtifactsKeeper(
        cache_root,
        settings,
        render_concurrency=selected_config.render_concurrency,
    )
    state = TokenState(cache_root / "state", settings.collection_size)

    source: TokenDataSource
    if token_source is not None:
        source = token_source
    elif selected_config.chain_enabled:
        assert selected_config.contract_address is not None
        assert selected_config.expected_chain_id is not None
        assert selected_config.expected_runtime_code_hash is not None
        source = await Web3TokenDataSource.connect(
            rpc_url=selected_config.rpc_url,
            contract_address=selected_config.contract_address,
            abi_path=selected_config.abi_path,
            expected_chain_id=selected_config.expected_chain_id,
            expected_runtime_code_hash=selected_config.expected_runtime_code_hash,
            expected_categories_sha256=settings.categories_sha256,
            expected_collection_size=settings.collection_size,
            expected_random_category_count=len(settings.categories) * 2,
            request_timeout_seconds=selected_config.request_timeout_seconds,
        )
    else:
        source = DisabledTokenDataSource()

    generator = MetaGenerator(
        keeper,
        state,
        source,
        settings,
        selected_config.public_base_url,
    )
    app = web.Application(middlewares=[error_middleware])
    app[CONFIG_KEY] = selected_config
    app[SETTINGS_KEY] = settings
    app[KEEPER_KEY] = keeper
    app[GENERATOR_KEY] = generator
    app[SOURCE_KEY] = source
    app[CACHE_ROOT_KEY] = cache_root
    app.add_routes(
        [
            web.get("/health", health),
            web.get("/token/{id}", token_meta),
            web.get("/image/{id}", image),
            web.get("/external/{id}", external),
        ]
    )
    app.on_cleanup.append(_close_source)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = AppConfig.from_env()
    web.run_app(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
