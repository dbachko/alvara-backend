from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from errors import ConfigurationError
from smart_client import Web3TokenDataSource


class _Call:
    async def call(self) -> int:
        return 123


class _Functions:
    def getData(self, token_id: int) -> _Call:  # noqa: N802 - Solidity ABI name
        assert token_id == 7
        return _Call()

    def traitDataManifest(self) -> _Call:  # noqa: N802 - Solidity ABI name
        call = _Call()

        async def manifest() -> tuple[int, bytes, bytes, int, int]:
            return (1, bytes.fromhex("11" * 32), bytes.fromhex("33" * 32), 3, 2)

        call.call = manifest
        return call


class _Eth:
    def __init__(self, chain_id: int, code: bytes) -> None:
        self._chain_id = chain_id
        self._code = code

    @property
    def chain_id(self):
        async def resolve() -> int:
            return self._chain_id

        return resolve()

    async def get_code(self, address: str) -> bytes:
        assert address == "0x1111111111111111111111111111111111111111"
        return self._code

    def contract(self, *, address: str, abi: list[dict]):
        assert address == "0x1111111111111111111111111111111111111111"
        assert any(entry.get("name") == "getData" for entry in abi)
        return SimpleNamespace(functions=_Functions())


def _install_fake_web3(monkeypatch, *, chain_id: int = 31337, code: bytes = b"\x01") -> None:
    module = ModuleType("web3")

    class AsyncHTTPProvider:
        def __init__(self, url: str, request_kwargs: dict) -> None:
            assert url == "http://127.0.0.1:8545"
            assert request_kwargs == {"timeout": 1.0}

    class AsyncWeb3:
        def __init__(self, provider: AsyncHTTPProvider) -> None:
            self.provider = provider
            self.eth = _Eth(chain_id, code)

        @staticmethod
        def to_checksum_address(address: str) -> str:
            return address

        @staticmethod
        def keccak(value: bytes) -> bytes:
            del value
            return bytes.fromhex("22" * 32)

    module.AsyncHTTPProvider = AsyncHTTPProvider
    module.AsyncWeb3 = AsyncWeb3
    monkeypatch.setitem(sys.modules, "web3", module)


async def _connect(abi_path):
    return await Web3TokenDataSource.connect(
        rpc_url="http://127.0.0.1:8545",
        contract_address="0x1111111111111111111111111111111111111111",
        abi_path=abi_path,
        expected_chain_id=31337,
        expected_runtime_code_hash=f"0x{'22' * 32}",
        expected_categories_sha256="11" * 32,
        expected_collection_size=3,
        expected_random_category_count=2,
        request_timeout_seconds=1.0,
    )


async def test_connect_verifies_chain_code_and_reads_genome(monkeypatch, miniature_config) -> None:
    _install_fake_web3(monkeypatch)

    source = await _connect(miniature_config.abi_path)

    assert await source.get_token_data(7) == 123


async def test_connect_rejects_wrong_chain(monkeypatch, miniature_config) -> None:
    _install_fake_web3(monkeypatch, chain_id=1)

    with pytest.raises(ConfigurationError, match="does not match"):
        await _connect(miniature_config.abi_path)


async def test_connect_rejects_address_without_code(monkeypatch, miniature_config) -> None:
    _install_fake_web3(monkeypatch, code=b"")

    with pytest.raises(ConfigurationError, match="has no bytecode"):
        await _connect(miniature_config.abi_path)


async def test_connect_rejects_unapproved_runtime_code(monkeypatch, miniature_config) -> None:
    _install_fake_web3(monkeypatch)

    with pytest.raises(ConfigurationError, match="runtime code hash"):
        await Web3TokenDataSource.connect(
            rpc_url="http://127.0.0.1:8545",
            contract_address="0x1111111111111111111111111111111111111111",
            abi_path=miniature_config.abi_path,
            expected_chain_id=31337,
            expected_runtime_code_hash=f"0x{'44' * 32}",
            expected_categories_sha256="11" * 32,
            expected_collection_size=3,
            expected_random_category_count=2,
            request_timeout_seconds=1.0,
        )
