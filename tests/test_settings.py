from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from collection_settings import load_collection_settings
from errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[1]


def test_real_settings_and_assets_are_internally_consistent() -> None:
    settings = load_collection_settings(ROOT / "settings.json")

    assert settings.collection_size == 10_000
    assert (
        settings.categories_sha256
        == "111233cde9dd315253ab7db062f1ae406d9acf2d29262b4bdc05bd8697d7c4bc"
    )
    assert len(settings.categories) == 5
    assert all(len(category.attributes) == 7 for category in settings.categories)

    paths = list(settings.iter_asset_paths())
    assert len(paths) == 350
    for resolution, path in paths:
        with Image.open(path) as image:
            assert image.size == (resolution, resolution)
            assert image.mode == "RGBA"

    for resolution in (350, 3000):
        hashes = {
            hashlib.sha256(path.read_bytes()).hexdigest()
            for current_resolution, path in paths
            if current_resolution == resolution
        }
        assert len(hashes) == 35


def test_asset_path_escape_is_rejected(miniature_settings: Path) -> None:
    document = json.loads(miniature_settings.read_text(encoding="utf-8"))
    document["categories"][0]["attributes"][0]["options"][0]["pics"][0]["path"] = "../outside.png"
    miniature_settings.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="contained relative path"):
        load_collection_settings(miniature_settings)


def test_negative_layer_z_matches_generator_schema(miniature_settings: Path) -> None:
    document = json.loads(miniature_settings.read_text(encoding="utf-8"))
    document["categories"][0]["attributes"][0]["options"][0]["pics"][0]["z"] = -1
    miniature_settings.write_text(json.dumps(document), encoding="utf-8")

    settings = load_collection_settings(miniature_settings)

    assert settings.categories[0].attributes[0].options[0].pictures[0].z == -1
