from __future__ import annotations

import json
from pathlib import Path

import pytest

import utils
from token_state import TokenState, TokenStatus


@pytest.mark.asyncio
async def test_state_round_trip_preserves_token_zero_and_last_token(tmp_path: Path) -> None:
    unrelated = tmp_path / "do-not-delete.txt"
    unrelated.write_text("owned by someone else", encoding="utf-8")
    state = TokenState(tmp_path, 10_000)
    state.tokens[0].status = TokenStatus.NOT_REROLLED
    state.tokens[0].data = 123
    state.tokens[9_999].status = TokenStatus.REROLLED
    state.tokens[9_999].data = 456

    await state.dump_token_state(0)
    await state.dump_token_state(9_999)
    restored = TokenState(tmp_path, 10_000)

    assert restored.tokens[0].data == 123
    assert restored.tokens[0].status is TokenStatus.NOT_REROLLED
    assert restored.tokens[9_999].data == 456
    assert restored.tokens[9_999].status is TokenStatus.REROLLED
    assert unrelated.read_text(encoding="utf-8") == "owned by someone else"


def test_atomic_json_failure_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "state"
    destination.write_text(json.dumps({"old": True}), encoding="utf-8")

    def fail_replace(source: str | Path, target: str | Path) -> None:
        del source, target
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(utils.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        utils.atomic_write_json(destination, {"new": True})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob(".alvara-*.tmp")) == []
