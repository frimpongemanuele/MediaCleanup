"""Shared media identification and planned filesystem operations."""

from __future__ import annotations

from pathlib import Path
from .naming import (
    VIDEO_EXTS,
    SUB_EXTS,
    INFO_EXTS,
)
from .filesystem import (
    safe_check,
    safe_rename,
    occupied,
    safe_is_file,
)

def is_video_file(path: Path) -> bool:
    return safe_is_file(path) and path.suffix.lower() in VIDEO_EXTS


def is_sub_file(path: Path) -> bool:
    return safe_is_file(path) and path.suffix.lower() in SUB_EXTS


def is_info_file(path: Path) -> bool:
    return safe_is_file(path) and path.suffix.lower() in INFO_EXTS


def unique_path(path: Path) -> Path:
    if not occupied(path):
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} - Version {counter}{path.suffix}")
        if not occupied(candidate):
            return candidate
        counter += 1


def unique_folder_path(path: Path) -> Path:
    if not occupied(path):
        return path

    counter = 2
    while True:
        candidate = path.parent / f"{path.name} - {counter}"
        if not occupied(candidate):
            return candidate
        counter += 1


def rename_item(old_path: Path, new_path: Path) -> Path:
    safe_check(old_path)
    safe_check(new_path)
    if old_path == new_path:
        return old_path

    if old_path.name == new_path.name and old_path.parent == new_path.parent:
        return old_path

    target = unique_path(new_path)
    print(f"  {old_path.name}  ->  {target.name}")
    safe_rename(old_path, target)
    return target
