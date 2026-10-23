"""Bounded, deterministic generation and retrieval of token artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import image_mixer
from collection_settings import CollectionSettings
from errors import ArtifactGenerationError, ArtifactNotFound
from genome import TokenGenome
from utils import atomic_write_json, cleanup_stale_temp_files, fsync_directory, temporary_path

_VERSION_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactsKeeper:
    def __init__(
        self,
        directory: str | Path,
        settings: CollectionSettings,
        *,
        render_concurrency: int = 2,
    ) -> None:
        if render_concurrency < 1:
            raise ValueError("render concurrency must be at least 1")
        self.directory = Path(directory).resolve()
        self.meta_dir = self.directory / "meta"
        self.image_dir = self.directory / "image"
        self.external_dir = self.directory / "external"
        self.current_dir = self.directory / "current"
        self.settings = settings
        self._render_slots = asyncio.Semaphore(render_concurrency)

        for artifact_dir in (
            self.meta_dir,
            self.image_dir,
            self.external_dir,
            self.current_dir,
        ):
            artifact_dir.mkdir(parents=True, exist_ok=True)
            cleanup_stale_temp_files(artifact_dir)

    def _manifest_path(self, token_id: int) -> Path:
        return self.current_dir / f"{token_id}.json"

    @staticmethod
    def _read_version(path: Path) -> str:
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactNotFound(f"artifact manifest does not exist: {path.name}") from exc
        version = document.get("version") if isinstance(document, dict) else None
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise ArtifactNotFound(f"artifact manifest is invalid: {path.name}")
        return version

    def _current_version(self, token_id: int) -> str:
        return self._read_version(self._manifest_path(token_id))

    def _version_paths(self, token_id: int, version: str) -> tuple[Path, Path, Path]:
        stem = f"{token_id}-{version}"
        return (
            self.meta_dir / f"{stem}.json",
            self.image_dir / f"{stem}.png",
            self.external_dir / f"{stem}.png",
        )

    def token_meta(self, token_id: int) -> Path:
        return self._version_paths(token_id, self._current_version(token_id))[0]

    def path_to_image(self, token_id: int) -> Path:
        return self._version_paths(token_id, self._current_version(token_id))[1]

    def path_to_external(self, token_id: int) -> Path:
        return self._version_paths(token_id, self._current_version(token_id))[2]

    def bundle_exists(self, token_id: int) -> bool:
        """Only treat a cached token as complete when all public artifacts exist."""

        try:
            paths = self._version_paths(token_id, self._current_version(token_id))
        except ArtifactNotFound:
            return False
        return all(path.is_file() for path in paths)

    def _layers(self, genome: TokenGenome, resolution: int) -> list[image_mixer.Layer]:
        category = self.settings.categories[genome.category_id]
        layers: list[image_mixer.Layer] = []
        for attribute_index, option_index in enumerate(genome.options):
            attribute = category.attributes[attribute_index]
            option = attribute.options[option_index]
            for picture in option.pictures:
                layers.append(
                    image_mixer.Layer(
                        path=self.settings.asset_path(resolution, category, attribute, picture),
                        z=picture.z,
                    )
                )
        return layers

    @staticmethod
    def _write_json_temp(path: Path, content: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())

    def _create_bundle_sync(self, genome: TokenGenome, metadata: dict[str, Any]) -> None:
        encoded_metadata = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        version = hashlib.sha256(
            genome.raw.to_bytes(32, "big") + b"\0" + encoded_metadata
        ).hexdigest()
        metadata_destination, image_destination, external_destination = self._version_paths(
            genome.token_id, version
        )
        with (
            temporary_path(self.image_dir) as image_temp,
            temporary_path(self.external_dir) as external_temp,
            temporary_path(self.meta_dir) as metadata_temp,
        ):
            image_resolution = self.settings.image_resolution
            external_resolution = self.settings.external_resolution
            image_mixer.mix(
                self._layers(genome, image_resolution),
                image_temp,
                expected_size=(image_resolution, image_resolution),
            )
            image_mixer.mix(
                self._layers(genome, external_resolution),
                external_temp,
                expected_size=(external_resolution, external_resolution),
            )
            self._write_json_temp(metadata_temp, metadata)

            # Versioned files remain invisible until the single current-manifest swap.
            os.replace(image_temp, image_destination)
            os.replace(external_temp, external_destination)
            os.replace(metadata_temp, metadata_destination)
            fsync_directory(self.image_dir)
            fsync_directory(self.external_dir)
            fsync_directory(self.meta_dir)
            atomic_write_json(self._manifest_path(genome.token_id), {"version": version})

    async def create_bundle(self, genome: TokenGenome, metadata: dict[str, Any]) -> None:
        try:
            async with self._render_slots:
                await asyncio.to_thread(self._create_bundle_sync, genome, metadata)
        except ArtifactGenerationError:
            raise
        except Exception as exc:
            raise ArtifactGenerationError(
                f"failed to generate artifacts for token {genome.token_id}"
            ) from exc

    async def tombstone(self, token_id: int) -> None:
        """Stop serving a cached generation after the chain confirms a burn."""

        def remove_manifest() -> None:
            self._manifest_path(token_id).unlink(missing_ok=True)
            fsync_directory(self.current_dir)

        await asyncio.to_thread(remove_manifest)

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ArtifactNotFound(f"artifact does not exist: {path.name}") from exc

    async def image_content(self, token_id: int) -> bytes:
        return await asyncio.to_thread(self._read_bytes, self.path_to_image(token_id))

    async def external_content(self, token_id: int) -> bytes:
        return await asyncio.to_thread(self._read_bytes, self.path_to_external(token_id))

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                content = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactNotFound(f"metadata does not exist: {path.name}") from exc
        if not isinstance(content, dict):
            raise ArtifactNotFound(f"metadata is invalid: {path.name}")
        return content

    async def token_meta_content(self, token_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_json, self.token_meta(token_id))
