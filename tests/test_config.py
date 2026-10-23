from __future__ import annotations

from dataclasses import replace

import pytest

from errors import ConfigurationError


def test_real_chain_requires_expected_chain_id(miniature_config) -> None:
    configured = replace(
        miniature_config,
        contract_address="0x0000000000000000000000000000000000000001",
    )
    with pytest.raises(ConfigurationError, match="expected chain ID"):
        configured.validate()


def test_default_configuration_is_chain_disabled(miniature_config) -> None:
    miniature_config.validate()
    assert miniature_config.chain_enabled is False
    assert miniature_config.host == "127.0.0.1"
    assert miniature_config.rpc_url == "http://127.0.0.1:8545"


def test_real_chain_requires_approved_runtime_code_hash(miniature_config) -> None:
    configured = replace(
        miniature_config,
        contract_address="0x0000000000000000000000000000000000000001",
        expected_chain_id=31337,
    )
    with pytest.raises(ConfigurationError, match="runtime code hash"):
        configured.validate()
