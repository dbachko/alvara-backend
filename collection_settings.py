"""Validated collection settings and asset-path resolution."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from errors import ConfigurationError

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_PACKED_OPTIONS = 32
_LEGACY_ATTRIBUTE_COUNT = 7


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{context} must be an array")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{context} must be a non-empty string")
    return value


def _integer(
    value: Any,
    context: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationError(f"{context} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{context} must be an integer <= {maximum}")
    return value


def _safe_segment(value: Any, context: str) -> str:
    segment = _text(value, context)
    if not _SAFE_SEGMENT_RE.fullmatch(segment):
        raise ConfigurationError(
            f"{context} must contain only letters, digits, underscores, or hyphens"
        )
    return segment


def _relative_asset_path(value: Any, context: str) -> PurePosixPath:
    raw = _text(value, context)
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ConfigurationError(f"{context} must be a contained relative path")
    return path


def _contained(root: Path, candidate: Path, context: str) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ConfigurationError(f"{context} escapes the configured asset root") from exc
    return resolved_candidate


@dataclass(frozen=True, slots=True)
class PictureSpec:
    relative_path: PurePosixPath
    z: int


@dataclass(frozen=True, slots=True)
class OptionSpec:
    name: str
    pictures: tuple[PictureSpec, ...]


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    name: str
    options: tuple[OptionSpec, ...]


@dataclass(frozen=True, slots=True)
class CategorySpec:
    name: str
    size: int
    attributes: tuple[AttributeSpec, ...]
    ignored: tuple[tuple[int, int, int, int], ...]
    included: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class CollectionSettings:
    source_path: Path
    asset_root: Path
    image_resolution: int
    external_resolution: int
    categories: tuple[CategorySpec, ...]
    categories_sha256: str

    @property
    def collection_size(self) -> int:
        return sum(category.size for category in self.categories)

    def asset_path(
        self,
        resolution: int,
        category: CategorySpec,
        attribute: AttributeSpec,
        picture: PictureSpec,
    ) -> Path:
        base = self.asset_root / str(resolution) / category.name / attribute.name
        candidate = base.joinpath(*picture.relative_path.parts)
        return _contained(self.asset_root, candidate, "picture path")

    def iter_asset_paths(self) -> Iterable[tuple[int, Path]]:
        for resolution in (self.image_resolution, self.external_resolution):
            for category in self.categories:
                for attribute in category.attributes:
                    for option in attribute.options:
                        for picture in option.pictures:
                            yield (
                                resolution,
                                self.asset_path(resolution, category, attribute, picture),
                            )


def _validate_option_indexes(
    category_name: str,
    attributes: tuple[AttributeSpec, ...],
    values: tuple[int, ...],
    context: str,
) -> None:
    if len(values) != len(attributes):
        raise ConfigurationError(
            f"{category_name} {context} must contain {len(attributes)} options"
        )
    for index, option_index in enumerate(values):
        if option_index >= len(attributes[index].options):
            raise ConfigurationError(f"{category_name} {context} option {index} is out of range")


def load_collection_settings(path: str | Path) -> CollectionSettings:
    source_path = Path(path).resolve()
    try:
        with source_path.open("r", encoding="utf-8") as handle:
            raw = _mapping(json.load(handle), "settings")
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read collection settings: {source_path}") from exc

    assets_value = _relative_asset_path(raw.get("assets_path"), "assets_path")
    asset_root = _contained(
        source_path.parent,
        source_path.parent.joinpath(*assets_value.parts),
        "assets_path",
    )
    if not asset_root.is_dir():
        raise ConfigurationError(f"asset root does not exist: {asset_root}")

    image_resolution = _integer(raw.get("image"), "image resolution", minimum=1)
    external_resolution = _integer(raw.get("external"), "external resolution", minimum=1)
    categories_raw = _list(raw.get("categories"), "categories")
    if not categories_raw:
        raise ConfigurationError("categories must not be empty")
    if len(categories_raw) * 2 > _MAX_PACKED_OPTIONS:
        raise ConfigurationError("too many categories for the legacy 5-bit category field")

    categories: list[CategorySpec] = []
    category_names: set[str] = set()
    for category_index, category_value in enumerate(categories_raw):
        category_raw = _mapping(category_value, f"category {category_index}")
        category_name = _safe_segment(category_raw.get("name"), f"category {category_index} name")
        if category_name in category_names:
            raise ConfigurationError(f"duplicate category name: {category_name}")
        category_names.add(category_name)
        category_size = _integer(category_raw.get("size"), f"{category_name} size", minimum=1)

        attributes_raw = _list(category_raw.get("attributes"), f"{category_name} attributes")
        if len(attributes_raw) != _LEGACY_ATTRIBUTE_COUNT:
            raise ConfigurationError(
                f"{category_name} must have exactly {_LEGACY_ATTRIBUTE_COUNT} attributes"
            )
        attributes: list[AttributeSpec] = []
        attribute_names: set[str] = set()
        for attribute_index, attribute_value in enumerate(attributes_raw):
            attribute_raw = _mapping(
                attribute_value, f"{category_name} attribute {attribute_index}"
            )
            attribute_name = _safe_segment(
                attribute_raw.get("name"),
                f"{category_name} attribute {attribute_index} name",
            )
            if attribute_name in attribute_names:
                raise ConfigurationError(
                    f"duplicate attribute name in {category_name}: {attribute_name}"
                )
            attribute_names.add(attribute_name)
            options_raw = _list(
                attribute_raw.get("options"),
                f"{category_name}.{attribute_name} options",
            )
            if not 1 <= len(options_raw) <= _MAX_PACKED_OPTIONS:
                raise ConfigurationError(f"{category_name}.{attribute_name} must have 1-32 options")
            options: list[OptionSpec] = []
            for option_index, option_value in enumerate(options_raw):
                option_raw = _mapping(
                    option_value,
                    f"{category_name}.{attribute_name} option {option_index}",
                )
                option_name = _text(
                    option_raw.get("name"),
                    f"{category_name}.{attribute_name} option {option_index} name",
                )
                pictures_raw = _list(
                    option_raw.get("pics"),
                    f"{category_name}.{attribute_name}.{option_name} pictures",
                )
                if not pictures_raw:
                    raise ConfigurationError(
                        f"{category_name}.{attribute_name}.{option_name} needs a picture"
                    )
                pictures: list[PictureSpec] = []
                for picture_index, picture_value in enumerate(pictures_raw):
                    picture_raw = _mapping(
                        picture_value,
                        f"{category_name}.{attribute_name}.{option_name} picture {picture_index}",
                    )
                    pictures.append(
                        PictureSpec(
                            relative_path=_relative_asset_path(
                                picture_raw.get("path"),
                                f"{category_name}.{attribute_name}.{option_name} picture path",
                            ),
                            z=_integer(
                                picture_raw.get("z"),
                                f"{category_name}.{attribute_name}.{option_name} z",
                                minimum=-(1 << 31),
                                maximum=(1 << 31) - 1,
                            ),
                        )
                    )
                options.append(OptionSpec(option_name, tuple(pictures)))
            attributes.append(AttributeSpec(attribute_name, tuple(options)))

        attributes_tuple = tuple(attributes)
        ignored: list[tuple[int, int, int, int]] = []
        for ignored_index, ignored_value in enumerate(
            _list(category_raw.get("ignored"), f"{category_name} ignored")
        ):
            values_raw = _list(ignored_value, f"{category_name} ignored rule {ignored_index}")
            if len(values_raw) != 4:
                raise ConfigurationError(
                    f"{category_name} ignored rule {ignored_index} must have 4 integers"
                )
            values = tuple(
                _integer(value, f"{category_name} ignored rule {ignored_index}")
                for value in values_raw
            )
            first_position, first_option, second_position, second_option = values
            if first_position >= len(attributes_tuple) or second_position >= len(attributes_tuple):
                raise ConfigurationError(
                    f"{category_name} ignored rule {ignored_index} position is out of range"
                )
            if first_option >= len(attributes_tuple[first_position].options) or (
                second_option >= len(attributes_tuple[second_position].options)
            ):
                raise ConfigurationError(
                    f"{category_name} ignored rule {ignored_index} option is out of range"
                )
            ignored.append((first_position, first_option, second_position, second_option))

        included: list[tuple[int, ...]] = []
        for included_index, included_value in enumerate(
            _list(category_raw.get("included"), f"{category_name} included")
        ):
            values = tuple(
                _integer(
                    value,
                    f"{category_name} included genome {included_index} option",
                )
                for value in _list(
                    included_value,
                    f"{category_name} included genome {included_index}",
                )
            )
            _validate_option_indexes(
                category_name,
                attributes_tuple,
                values,
                f"included genome {included_index}",
            )
            included.append(values)

        categories.append(
            CategorySpec(
                name=category_name,
                size=category_size,
                attributes=attributes_tuple,
                ignored=tuple(ignored),
                included=tuple(included),
            )
        )

    settings = CollectionSettings(
        source_path=source_path,
        asset_root=asset_root,
        image_resolution=image_resolution,
        external_resolution=external_resolution,
        categories=tuple(categories),
        categories_sha256=hashlib.sha256(
            json.dumps(
                categories_raw,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    )
    if settings.collection_size < 1:
        raise ConfigurationError("collection size must be positive")

    for _resolution, asset_path in settings.iter_asset_paths():
        if not asset_path.is_file():
            raise ConfigurationError(f"referenced asset does not exist: {asset_path}")
    return settings
