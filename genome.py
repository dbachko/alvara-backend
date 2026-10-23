"""Decoder and validation for the historical 41-bit Alvara genome."""

from __future__ import annotations

from dataclasses import dataclass

from collection_settings import CollectionSettings
from errors import InvalidGenome, TokenNotFound

ATTRIBUTE_COUNT = 7
OPTION_BITS = 5
OPTIONS_BITS = ATTRIBUTE_COUNT * OPTION_BITS
CATEGORY_BITS = 5
REROLL_SHIFT = OPTIONS_BITS + CATEGORY_BITS
GENOME_BITS = REROLL_SHIFT + 1
OPTION_MASK = (1 << OPTION_BITS) - 1
CATEGORY_MASK = (1 << CATEGORY_BITS) - 1
MISSING_TOKEN_SENTINEL = (1 << GENOME_BITS) - 1


@dataclass(frozen=True, slots=True)
class TokenGenome:
    token_id: int
    raw: int
    rerolled: bool
    random_category_id: int
    category_id: int
    options: tuple[int, ...]


def matches_exclusion(options: tuple[int, ...], rule: tuple[int, int, int, int]) -> bool:
    first_position, first_option, second_position, second_option = rule
    return options[first_position] == first_option and options[second_position] == second_option


def decode_genome(value: int, token_id: int, settings: CollectionSettings) -> TokenGenome:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidGenome("contract genome must be an integer")
    if value == MISSING_TOKEN_SENTINEL:
        raise TokenNotFound(f"token {token_id} is not minted or has been burned")
    if value < 0 or value >= (1 << GENOME_BITS):
        raise InvalidGenome("contract genome exceeds the legacy 41-bit layout")

    packed_options = value & ((1 << OPTIONS_BITS) - 1)
    reversed_options: list[int] = []
    for _index in range(ATTRIBUTE_COUNT):
        reversed_options.append(packed_options & OPTION_MASK)
        packed_options >>= OPTION_BITS
    options = tuple(reversed(reversed_options))

    random_category_id = (value >> OPTIONS_BITS) & CATEGORY_MASK
    category_id = random_category_id // 2
    if category_id >= len(settings.categories):
        raise InvalidGenome("contract genome category is out of range")
    category = settings.categories[category_id]
    if len(category.attributes) != ATTRIBUTE_COUNT:
        raise InvalidGenome("collection schema does not match the legacy genome")

    for index, option_index in enumerate(options):
        if option_index >= len(category.attributes[index].options):
            raise InvalidGenome(
                f"contract genome option {index} is out of range for {category.name}"
            )
    for rule in category.ignored:
        if matches_exclusion(options, rule):
            raise InvalidGenome("contract genome violates an excluded trait combination")
    is_special = random_category_id % 2 == 1
    if is_special and options not in category.included:
        raise InvalidGenome("contract special-category genome is not in the included trait table")
    if not is_special and options in category.included:
        raise InvalidGenome("contract normal-category genome uses a reserved included trait vector")

    return TokenGenome(
        token_id=token_id,
        raw=value,
        rerolled=bool((value >> REROLL_SHIFT) & 1),
        random_category_id=random_category_id,
        category_id=category_id,
        options=options,
    )
