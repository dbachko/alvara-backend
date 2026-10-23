from __future__ import annotations

from pathlib import Path

import pytest

from collection_settings import load_collection_settings
from errors import InvalidGenome, TokenNotFound
from genome import MISSING_TOKEN_SENTINEL, REROLL_SHIFT, decode_genome

ROOT = Path(__file__).resolve().parents[1]


def _encode(options: list[int], *, random_category_id: int = 0, rerolled: bool = False) -> int:
    packed = 0
    for option in options:
        packed = (packed << 5) | option
    return (int(rerolled) << REROLL_SHIFT) | (random_category_id << 35) | packed


def test_decode_legacy_genome_and_reroll_flag() -> None:
    settings = load_collection_settings(ROOT / "settings.json")
    raw = _encode([0, 0, 0, 0, 0, 0, 1], rerolled=True)

    genome = decode_genome(raw, 0, settings)

    assert genome.token_id == 0
    assert genome.category_id == 0
    assert genome.options == (0, 0, 0, 0, 0, 0, 1)
    assert genome.rerolled is True


def test_special_genome_must_come_from_included_table() -> None:
    settings = load_collection_settings(ROOT / "settings.json")
    valid = _encode([0, 0, 0, 0, 0, 0, 0], random_category_id=1)
    invalid = _encode([3, 0, 0, 0, 0, 0, 0], random_category_id=1)

    assert decode_genome(valid, 3, settings).random_category_id == 1
    with pytest.raises(InvalidGenome, match="included trait table"):
        decode_genome(invalid, 3, settings)


def test_normal_genome_cannot_use_a_reserved_included_vector() -> None:
    settings = load_collection_settings(ROOT / "settings.json")
    reserved = _encode([0, 0, 0, 0, 0, 0, 0], random_category_id=0)

    with pytest.raises(InvalidGenome, match="reserved included trait vector"):
        decode_genome(reserved, 3, settings)


def test_excluded_trait_combination_is_rejected() -> None:
    settings = load_collection_settings(ROOT / "settings.json")
    # settings.json excludes background option 1 with earrings option 2.
    raw = _encode([1, 0, 2, 0, 0, 0, 0])

    with pytest.raises(InvalidGenome, match="excluded trait combination"):
        decode_genome(raw, 7, settings)


@pytest.mark.parametrize("raw", [MISSING_TOKEN_SENTINEL])
def test_missing_token_sentinel_is_not_rendered(raw: int) -> None:
    settings = load_collection_settings(ROOT / "settings.json")
    with pytest.raises(TokenNotFound):
        decode_genome(raw, 9, settings)


def test_high_bits_and_option_overflow_are_rejected() -> None:
    settings = load_collection_settings(ROOT / "settings.json")
    with pytest.raises(InvalidGenome, match="41-bit"):
        decode_genome(1 << 41, 1, settings)
    with pytest.raises(InvalidGenome, match="option 1"):
        decode_genome(_encode([0, 1, 0, 0, 0, 0, 0]), 1, settings)
