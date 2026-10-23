"""Derive an immutable namespace for generated metadata and image bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import PIL

from collection_settings import CollectionSettings
from config import AppConfig

CACHE_FORMAT_VERSION = 2


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_namespace(config: AppConfig, settings: CollectionSettings) -> str:
    """Bind cache reuse to every input that can change public artifact bytes."""

    assets = []
    seen: set[tuple[int, Path]] = set()
    for resolution, path in settings.iter_asset_paths():
        identity = (resolution, path)
        if identity in seen:
            continue
        seen.add(identity)
        assets.append(
            {
                "resolution": resolution,
                "path": path.relative_to(settings.asset_root).as_posix(),
                "sha256": _file_sha256(path),
            }
        )
    assets.sort(key=lambda item: (item["resolution"], item["path"]))

    manifest = {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "pillow_version": PIL.__version__,
        "categories_sha256": settings.categories_sha256,
        "collection_size": settings.collection_size,
        "image_resolution": settings.image_resolution,
        "external_resolution": settings.external_resolution,
        "public_base_url": config.public_base_url.rstrip("/"),
        "chain_id": config.expected_chain_id,
        "contract_address": (
            config.contract_address.lower() if config.contract_address is not None else None
        ),
        "runtime_code_hash": (
            config.expected_runtime_code_hash.lower()
            if config.expected_runtime_code_hash is not None
            else None
        ),
        "abi_sha256": _file_sha256(config.abi_path) if config.abi_path.is_file() else None,
        "assets": assets,
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
