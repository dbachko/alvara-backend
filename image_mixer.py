from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True, slots=True)
class Layer:
    path: Path
    z: int


def mix(
    layers: Sequence[Layer],
    destination: str | Path,
    *,
    expected_size: tuple[int, int] | None = None,
) -> Path:
    if not layers:
        raise ValueError("at least one image layer is required")
    ordered = sorted(layers, key=lambda layer: layer.z)

    with Image.open(ordered[0].path) as first:
        first.load()
        result = first.convert("RGBA")
    if expected_size is not None and result.size != expected_size:
        result.close()
        raise ValueError(f"unexpected image size for {ordered[0].path}: {result.size}")

    try:
        for layer in ordered[1:]:
            with Image.open(layer.path) as source:
                source.load()
                overlay = source.convert("RGBA")
            try:
                if overlay.size != result.size:
                    raise ValueError(f"layer size mismatch for {layer.path}: {overlay.size}")
                composed = Image.alpha_composite(result, overlay)
            finally:
                overlay.close()
            result.close()
            result = composed
        output_path = Path(destination)
        result.save(output_path, format="PNG")
        with output_path.open("rb") as output:
            os.fsync(output.fileno())
        return output_path
    finally:
        result.close()
