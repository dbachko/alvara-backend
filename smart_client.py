"""Typed async token-data sources."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from errors import ConfigurationError, UpstreamUnavailable

_REQUIRED_ABI = {
    "getData": {
        "inputs": ["uint256"],
        "outputs": ["uint256"],
        "stateMutability": "view",
    },
    "traitDataManifest": {
        "inputs": [],
        "outputs": ["uint256", "bytes32", "bytes32", "uint256", "uint256"],
        "stateMutability": "pure",
    },
}


@runtime_checkable
class TokenDataSource(Protocol):
    async def get_token_data(self, token_id: int) -> int:
        """Return the historical packed genome for a token."""


class DisabledTokenDataSource:
    async def get_token_data(self, token_id: int) -> int:
        del token_id
        raise UpstreamUnavailable(
            "chain reads are disabled; configure address and expected chain ID"
        )


def load_abi(path: str | Path) -> list[dict[str, Any]]:
    abi_path = Path(path)
    try:
        with abi_path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read ABI: {abi_path}") from exc
    abi = document.get("abi") if isinstance(document, dict) else document
    if not isinstance(abi, list) or not all(isinstance(entry, dict) for entry in abi):
        raise ConfigurationError("ABI must be an array or an artifact with an abi array")
    for name, expected in _REQUIRED_ABI.items():
        matches = [
            entry
            for entry in abi
            if entry.get("type") == "function"
            and entry.get("name") == name
            and [item.get("type") for item in entry.get("inputs", [])] == expected["inputs"]
            and [item.get("type") for item in entry.get("outputs", [])] == expected["outputs"]
            and entry.get("stateMutability") == expected["stateMutability"]
        ]
        if len(matches) != 1:
            raise ConfigurationError(f"ABI does not contain exactly one required {name} signature")
    return abi


def _hex32(value: Any, context: str) -> str:
    if isinstance(value, str):
        normalized = value.lower()
        if normalized.startswith("0x") and len(normalized) == 66:
            try:
                bytes.fromhex(normalized[2:])
            except ValueError as exc:
                raise ConfigurationError(f"{context} is not a valid bytes32 value") from exc
            return normalized
    try:
        raw = bytes(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{context} is not a valid bytes32 value") from exc
    if len(raw) != 32:
        raise ConfigurationError(f"{context} is not a valid bytes32 value")
    return f"0x{raw.hex()}"


class Web3TokenDataSource:
    def __init__(self, web3: Any, contract: Any) -> None:
        self._web3 = web3
        self._contract = contract

    @classmethod
    async def connect(
        cls,
        *,
        rpc_url: str,
        contract_address: str,
        abi_path: str | Path,
        expected_chain_id: int,
        expected_runtime_code_hash: str,
        expected_categories_sha256: str,
        expected_collection_size: int,
        expected_random_category_count: int,
        request_timeout_seconds: float,
    ) -> Web3TokenDataSource:
        try:
            from web3 import AsyncHTTPProvider, AsyncWeb3
        except ImportError as exc:
            raise ConfigurationError("web3 is required for configured chain reads") from exc

        abi = load_abi(abi_path)
        try:
            checksum_address = AsyncWeb3.to_checksum_address(contract_address)
            web3 = AsyncWeb3(
                AsyncHTTPProvider(
                    rpc_url,
                    request_kwargs={"timeout": request_timeout_seconds},
                )
            )
            actual_chain_id = await web3.eth.chain_id
            if actual_chain_id != expected_chain_id:
                raise ConfigurationError(
                    f"RPC chain ID {actual_chain_id} does not match expected chain ID "
                    f"{expected_chain_id}"
                )
            code = await web3.eth.get_code(checksum_address)
            if not code or bytes(code) in {b"", b"\x00"}:
                raise ConfigurationError(
                    "configured contract address has no bytecode on the expected chain"
                )
            actual_code_hash = _hex32(AsyncWeb3.keccak(bytes(code)), "runtime code hash")
            if actual_code_hash != expected_runtime_code_hash.lower():
                raise ConfigurationError(
                    "configured contract runtime code hash does not match the approved hash"
                )
            contract = web3.eth.contract(address=checksum_address, abi=abi)
            manifest = await contract.functions.traitDataManifest().call()
            if not isinstance(manifest, (list, tuple)) or len(manifest) != 5:
                raise ConfigurationError("contract returned an invalid trait-data manifest")
            (
                schema_version,
                categories_hash,
                words_hash,
                total_size,
                random_category_count,
            ) = manifest
            if schema_version != 1:
                raise ConfigurationError("contract trait-data schema version is unsupported")
            if _hex32(categories_hash, "contract categories hash") != (
                f"0x{expected_categories_sha256.lower()}"
            ):
                raise ConfigurationError("contract trait-data hash does not match local settings")
            _hex32(words_hash, "contract words hash")
            if total_size != expected_collection_size:
                raise ConfigurationError("contract trait-data supply does not match local settings")
            if random_category_count != expected_random_category_count:
                raise ConfigurationError(
                    "contract trait-data category count does not match local settings"
                )
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError("failed to verify the configured chain and contract") from exc
        return cls(web3, contract)

    async def get_token_data(self, token_id: int) -> int:
        try:
            result = await self._contract.functions.getData(token_id).call()
        except Exception as exc:
            raise UpstreamUnavailable("contract getData call failed") from exc
        if isinstance(result, bool) or not isinstance(result, int):
            raise UpstreamUnavailable("contract getData returned a non-integer genome")
        return result

    async def close(self) -> None:
        provider = getattr(self._web3, "provider", None)
        disconnect = getattr(provider, "disconnect", None)
        if disconnect is None:
            return
        result = disconnect()
        if inspect.isawaitable(result):
            await result
