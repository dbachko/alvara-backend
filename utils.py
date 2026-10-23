import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

TEMP_PREFIX = ".alvara-"
TEMP_SUFFIX = ".tmp"


def create_dir_if_not_exist(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


@contextmanager
def temporary_path(directory: str | Path) -> Iterator[Path]:
    target_directory = Path(directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX, dir=target_directory
    )
    os.close(descriptor)
    temp_path = Path(raw_path)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: str | Path, content: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with temporary_path(destination.parent) as temp_path:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
        fsync_directory(destination.parent)


def fsync_directory(path: str | Path) -> None:
    """Persist directory-entry changes on platforms that support directory fsync."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(Path(path), flags)
    except OSError:
        # Windows and some filesystems do not expose directories as fsync-able handles.
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            return
    finally:
        os.close(descriptor)


def cleanup_stale_temp_files(
    directory: str | Path,
    *,
    older_than_seconds: int = 3600,
    now: float | None = None,
) -> None:
    """Delete only temp files created by this application and only when stale."""

    cutoff = (time.time() if now is None else now) - older_than_seconds
    for candidate in Path(directory).glob(f"{TEMP_PREFIX}*{TEMP_SUFFIX}"):
        try:
            if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()
        except FileNotFoundError:
            continue
