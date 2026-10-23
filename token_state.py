"""Crash-safe local cache state keyed by the actual zero-based token ID."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from errors import StatePersistenceError
from utils import atomic_write_json, cleanup_stale_temp_files


class TokenStatus(IntEnum):
    NOT_SEEN = 1
    NOT_REROLLED = 2
    REROLLED = 3


@dataclass(slots=True)
class TokenRecord:
    status: TokenStatus = TokenStatus.NOT_SEEN
    data: int | None = None


class TokenState:
    def __init__(self, state_dir: str | Path, size: int) -> None:
        if size < 1:
            raise ValueError("state size must be positive")
        self.directory = Path(state_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        cleanup_stale_temp_files(self.directory)
        self.size = size
        self.locks = [asyncio.Lock() for _ in range(size)]
        self.tokens = [TokenRecord() for _ in range(size)]
        self._load_state()

    def path_for(self, token_id: int) -> Path:
        if not 0 <= token_id < self.size:
            raise IndexError("token ID is outside the state range")
        # Keep the historical extensionless filename while fixing its indexing.
        return self.directory / str(token_id)

    def _load_state(self) -> None:
        for token_id in range(self.size):
            path = self.path_for(token_id)
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    content = json.load(handle)
                if not isinstance(content, dict):
                    raise ValueError("state record must be an object")
                status = TokenStatus(content["state"])
                data = content["data"]
                if isinstance(data, bool) or not isinstance(data, int):
                    raise ValueError("state genome must be an integer")
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise StatePersistenceError(f"invalid state record for token {token_id}") from exc
            self.tokens[token_id] = TokenRecord(status=status, data=data)

    async def dump_token_state(self, token_id: int) -> None:
        record = self.tokens[token_id]
        if record.data is None:
            raise StatePersistenceError("cannot persist a token without genome data")
        try:
            await asyncio.to_thread(
                atomic_write_json,
                self.path_for(token_id),
                {"state": int(record.status), "data": record.data},
            )
        except OSError as exc:
            raise StatePersistenceError(f"failed to persist state for token {token_id}") from exc
