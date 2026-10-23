from __future__ import annotations

from pathlib import Path

import pytest

from collection_settings import load_collection_settings
from errors import StatePersistenceError
from meta_generator import MetaGenerator
from token_state import TokenState, TokenStatus


class StaticSource:
    async def get_token_data(self, token_id: int) -> int:
        del token_id
        return 1 << 35


class NoOpKeeper:
    def bundle_exists(self, token_id: int) -> bool:
        del token_id
        return False

    async def create_bundle(self, genome, metadata) -> None:
        del genome, metadata


@pytest.mark.asyncio
async def test_failed_state_write_does_not_leave_a_false_cache_hit(
    miniature_settings: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_collection_settings(miniature_settings)
    state = TokenState(tmp_path / "state", settings.collection_size)

    async def fail_dump(token_id: int) -> None:
        del token_id
        raise StatePersistenceError("simulated state failure")

    monkeypatch.setattr(state, "dump_token_state", fail_dump)
    generator = MetaGenerator(
        NoOpKeeper(),
        state,
        StaticSource(),
        settings,
        "http://127.0.0.1:8080",
    )

    with pytest.raises(StatePersistenceError, match="simulated state failure"):
        await generator.meta(0)

    assert state.tokens[0].data is None
    assert state.tokens[0].status is TokenStatus.NOT_SEEN
