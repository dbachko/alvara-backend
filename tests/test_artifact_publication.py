from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import artifacts_keeper as keeper_module
from artifacts_keeper import ArtifactsKeeper
from cache_identity import cache_namespace
from collection_settings import load_collection_settings
from errors import ArtifactGenerationError
from genome import TokenGenome


def _genome(raw: int, *, rerolled: bool = False) -> TokenGenome:
    return TokenGenome(
        token_id=0,
        raw=raw,
        rerolled=rerolled,
        random_category_id=0,
        category_id=0,
        options=(0, 0, 0, 0, 0, 0, 0),
    )


@pytest.mark.asyncio
async def test_failed_version_publish_keeps_previous_bundle_current(
    miniature_settings: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_collection_settings(miniature_settings)
    keeper = ArtifactsKeeper(tmp_path / "artifacts", settings)
    await keeper.create_bundle(_genome(0), {"name": "old"})
    old_metadata_path = keeper.token_meta(0)
    old_image_path = keeper.path_to_image(0)
    real_replace = keeper_module.os.replace

    def fail_external_publish(source: str | Path, destination: str | Path) -> None:
        destination_path = Path(destination)
        if destination_path.parent == keeper.external_dir and Path(source).suffix == ".tmp":
            raise OSError("simulated external-image publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(keeper_module.os, "replace", fail_external_publish)
    with pytest.raises(ArtifactGenerationError, match="failed to generate artifacts"):
        await keeper.create_bundle(_genome(1 << 40, rerolled=True), {"name": "new"})

    assert keeper.token_meta(0) == old_metadata_path
    assert keeper.path_to_image(0) == old_image_path
    assert await keeper.token_meta_content(0) == {"name": "old"}


def test_cache_namespace_changes_with_public_metadata_origin(
    miniature_config,
    miniature_settings: Path,
) -> None:
    settings = load_collection_settings(miniature_settings)
    original = cache_namespace(miniature_config, settings)
    changed = cache_namespace(
        replace(miniature_config, public_base_url="https://metadata.example"),
        settings,
    )

    assert original != changed
