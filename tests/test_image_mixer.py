from __future__ import annotations

from pathlib import Path

from PIL import Image

from image_mixer import Layer, mix


def test_alpha_composites_layers_in_z_order(tmp_path: Path) -> None:
    background = tmp_path / "background.png"
    overlay = tmp_path / "overlay.png"
    destination = tmp_path / "result.png"
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(background)
    Image.new("RGBA", (1, 1), (0, 0, 255, 128)).save(overlay)

    mix(
        [Layer(path=overlay, z=20), Layer(path=background, z=10)],
        destination,
        expected_size=(1, 1),
    )

    with Image.open(destination) as result:
        assert result.getpixel((0, 0)) == (127, 0, 128, 255)
