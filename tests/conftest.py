from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from config import AppConfig


@pytest.fixture
def miniature_settings(tmp_path: Path) -> Path:
    asset_root = tmp_path / "assets"
    attributes = []
    for attribute_index in range(7):
        attribute_name = f"attr{attribute_index}"
        attributes.append(
            {
                "name": attribute_name,
                "options": [
                    {
                        "name": f"option{attribute_index}",
                        "pics": [{"path": "layer.png", "z": attribute_index}],
                    }
                ],
            }
        )
        for resolution in (2, 4):
            destination = asset_root / str(resolution) / "cool" / attribute_name
            destination.mkdir(parents=True, exist_ok=True)
            color = (255, 0, 0, 255) if attribute_index == 0 else (0, 0, 0, 0)
            Image.new("RGBA", (resolution, resolution), color).save(
                destination / "layer.png", format="PNG"
            )

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "assets_path": "assets",
                "image": 2,
                "external": 4,
                "categories": [
                    {
                        "name": "cool",
                        "size": 3,
                        "attributes": attributes,
                        "ignored": [],
                        "included": [[0, 0, 0, 0, 0, 0, 0]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return settings_path


@pytest.fixture
def miniature_config(miniature_settings: Path, tmp_path: Path) -> AppConfig:
    return AppConfig(
        settings_path=miniature_settings,
        artifacts_dir=tmp_path / "artifacts",
        abi_path=Path(__file__).resolve().parents[1] / "abi" / "AlvaraStorage.json",
        public_base_url="http://127.0.0.1:8080",
    )
