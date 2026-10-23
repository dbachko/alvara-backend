"""Explicit, local-safe application configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from errors import ConfigurationError

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_int(name: str, value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _resolve(base_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


@dataclass(frozen=True, slots=True)
class AppConfig:
    settings_path: Path
    artifacts_dir: Path
    abi_path: Path
    host: str = "127.0.0.1"
    port: int = 8080
    public_base_url: str = "http://127.0.0.1:8080"
    rpc_url: str = "http://127.0.0.1:8545"
    contract_address: str | None = None
    expected_chain_id: int | None = None
    expected_runtime_code_hash: str | None = None
    request_timeout_seconds: float = 10.0
    render_concurrency: int = 2

    @property
    def chain_enabled(self) -> bool:
        return self.contract_address is not None

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> AppConfig:
        root = (base_dir or Path(__file__).resolve().parent).resolve()
        port = _parse_int("ALVARA_PORT", os.getenv("ALVARA_PORT"), 8080)
        chain_id = _parse_int("ALVARA_EXPECTED_CHAIN_ID", os.getenv("ALVARA_EXPECTED_CHAIN_ID"))
        render_concurrency = _parse_int(
            "ALVARA_RENDER_CONCURRENCY", os.getenv("ALVARA_RENDER_CONCURRENCY"), 2
        )
        try:
            timeout = float(os.getenv("ALVARA_RPC_TIMEOUT_SECONDS", "10"))
        except ValueError as exc:
            raise ConfigurationError("ALVARA_RPC_TIMEOUT_SECONDS must be numeric") from exc

        config = cls(
            settings_path=_resolve(root, os.getenv("ALVARA_SETTINGS_PATH", "settings.json")),
            artifacts_dir=_resolve(root, os.getenv("ALVARA_ARTIFACTS_DIR", "artifacts")),
            abi_path=_resolve(root, os.getenv("ALVARA_ABI_PATH", "abi/AlvaraStorage.json")),
            host=os.getenv("ALVARA_HOST", "127.0.0.1"),
            port=port if port is not None else 8080,
            public_base_url=os.getenv("ALVARA_PUBLIC_BASE_URL", "http://127.0.0.1:8080"),
            rpc_url=os.getenv("ALVARA_RPC_URL", "http://127.0.0.1:8545"),
            contract_address=_optional_text(os.getenv("ALVARA_CONTRACT_ADDRESS")),
            expected_chain_id=chain_id,
            expected_runtime_code_hash=_optional_text(
                os.getenv("ALVARA_EXPECTED_RUNTIME_CODE_HASH")
            ),
            request_timeout_seconds=timeout,
            render_concurrency=(render_concurrency if render_concurrency is not None else 2),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.settings_path.is_file():
            raise ConfigurationError(
                f"collection settings file does not exist: {self.settings_path}"
            )
        if not self.host.strip():
            raise ConfigurationError("host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("port must be between 1 and 65535")
        if self.render_concurrency < 1:
            raise ConfigurationError("render concurrency must be at least 1")
        if self.request_timeout_seconds <= 0:
            raise ConfigurationError("RPC timeout must be greater than zero")

        public_url = urlparse(self.public_base_url)
        if public_url.scheme not in {"http", "https"} or not public_url.hostname:
            raise ConfigurationError("public base URL must be an absolute http(s) URL")
        if public_url.username or public_url.password or public_url.query or public_url.fragment:
            raise ConfigurationError(
                "public base URL must not contain credentials, a query, or a fragment"
            )
        rpc_url = urlparse(self.rpc_url)
        if rpc_url.scheme not in {"http", "https"} or not rpc_url.hostname:
            raise ConfigurationError("RPC URL must be an absolute http(s) URL")

        if self.contract_address is None:
            if self.expected_chain_id is not None or self.expected_runtime_code_hash is not None:
                raise ConfigurationError(
                    "expected chain ID/code hash requires an explicit contract address"
                )
            return

        if not _ADDRESS_RE.fullmatch(self.contract_address):
            raise ConfigurationError("contract address must be a 20-byte 0x-prefixed hex address")
        if self.expected_chain_id is None or self.expected_chain_id <= 0:
            raise ConfigurationError(
                "real chain reads require an explicit positive expected chain ID"
            )
        if self.expected_runtime_code_hash is None or not _HASH_RE.fullmatch(
            self.expected_runtime_code_hash
        ):
            raise ConfigurationError(
                "real chain reads require an explicit 32-byte expected runtime code hash"
            )
        if not self.abi_path.is_file():
            raise ConfigurationError(f"ABI file does not exist: {self.abi_path}")
