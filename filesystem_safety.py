"""Filesystem boundaries for MediaCleanup's rename and mkdir operations."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Iterator


class UnsafePathError(ValueError):
    """A path cannot be used safely within the selected library."""


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _linklike(path: Path) -> bool:
    """Reject symbolic links and Windows reparse points, including junctions."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    flags = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        flags & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _check_components(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        if _linklike(component):
            raise UnsafePathError(f"Refusing link or reparse point: {component}")


class FilesystemGuard:
    def __init__(self, root: Path, *, allow_root_rename: bool = False):
        self.root = _absolute(root)
        if self.root == self.root.parent:
            raise UnsafePathError("Choose a media folder, not a filesystem root.")
        _check_components(self.root)
        if not self.root.is_dir():
            raise UnsafePathError("The selected media folder does not exist.")
        self.allow_root_rename = allow_root_rename

    def check(self, path: Path) -> Path:
        candidate = _absolute(path)
        if candidate != self.root and self.root not in candidate.parents:
            raise UnsafePathError(f"Path outside the selected media folder: {candidate}")
        _check_components(candidate)
        return candidate

    def children(self, path: Path) -> list[Path]:
        folder = self.check(path)
        # Do not enumerate the contents of linked directories or junctions.
        return [child for child in folder.iterdir() if not _linklike(child)]

    def walk(self, path: Path) -> Iterator[Path]:
        pending = [self.check(path)]
        while pending:
            for child in self.children(pending.pop()):
                yield child
                if child.is_dir():
                    pending.append(child)

    def mkdir(self, path: Path) -> None:
        target = self.check(path)
        target.mkdir(exist_ok=True)

    def rename(self, source: Path, destination: Path) -> None:
        old = self.check(source)
        new = _absolute(destination)
        renaming_root = old == self.root and new != old
        if renaming_root:
            if not self.allow_root_rename or new.parent != self.root.parent:
                raise UnsafePathError("The selected root may only be renamed in single-folder mode.")
            _check_components(new)
        else:
            self.check(new)
        if old == new:
            return
        if os.path.lexists(new):
            raise FileExistsError(f"Destination already exists: {new}")
        old.rename(new)
        if renaming_root:
            self.root = new


_guard: FilesystemGuard | None = None


def configure_root(root: Path, *, allow_root_rename: bool = False) -> Path:
    global _guard
    _guard = FilesystemGuard(root, allow_root_rename=allow_root_rename)
    return _guard.root


def _active() -> FilesystemGuard:
    if _guard is None:
        raise UnsafePathError("Configure the media root before accessing the filesystem.")
    return _guard


def safe_children(path: Path) -> list[Path]:
    return _active().children(path)


def safe_walk(path: Path) -> Iterator[Path]:
    return _active().walk(path)


def safe_check(path: Path) -> Path:
    return _active().check(path)


def safe_rename(source: Path, destination: Path) -> None:
    _active().rename(source, destination)


def safe_mkdir(path: Path) -> None:
    _active().mkdir(path)


def occupied(path: Path) -> bool:
    """Treat even dangling symlinks as occupied names."""
    return os.path.lexists(path)
