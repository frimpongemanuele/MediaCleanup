"""Build a deterministic filesystem plan without touching the media library."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Iterator

from filesystem_safety import FilesystemGuard, UnsafePathError, _absolute, _linklike


Identity = tuple[int, int]


def identity(path: Path) -> Identity:
    info = path.lstat()
    return (info.st_dev, info.st_ino)


@dataclass(frozen=True)
class Operation:
    kind: str
    target: Path
    source: Path | None = None
    source_id: Identity | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "target": str(self.target),
            "source": str(self.source) if self.source is not None else None,
            "source_id": list(self.source_id) if self.source_id is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Operation:
        if not isinstance(data, dict):
            raise ValueError("Invalid operation.")
        kind = data.get("kind")
        target = _plan_path(data.get("target"))
        if kind == "mkdir" and data.get("source") is None and data.get("source_id") is None:
            return cls(kind, target)
        if kind == "rename":
            sid = data.get("source_id")
            if isinstance(sid, list) and len(sid) == 2 and all(type(n) is int for n in sid):
                return cls(kind, target, _plan_path(data.get("source")), tuple(sid))
        raise ValueError("Invalid operation.")


def _plan_path(value: object) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("Expected an absolute path.")
    return _absolute(Path(value))


@dataclass(frozen=True)
class Plan:
    root: Path
    single: bool
    operations: tuple[Operation, ...]

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "root": str(self.root),
            "single": self.single,
            "operations": [op.to_dict() for op in self.operations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Plan:
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported plan format.")
        if type(data.get("single")) is not bool or not isinstance(data.get("operations"), list):
            raise ValueError("Invalid plan.")
        return cls(
            _plan_path(data.get("root")), data["single"],
            tuple(Operation.from_dict(op) for op in data["operations"]),
        )


@dataclass(frozen=True)
class _Entry:
    kind: str
    identity: Identity | None


class Planner:
    """An in-memory directory topology; never opens or copies media files."""

    def __init__(self, root: Path, *, single: bool = False):
        guard = FilesystemGuard(root, allow_root_rename=single)
        self.initial_root = self.root = guard.root
        self.single = single
        self.operations: list[Operation] = []
        self.entries: dict[Path, _Entry] = {}
        self._scan(self.root)

    def _scan(self, root: Path) -> None:
        pending = [root]
        while pending:
            path = pending.pop()
            info = path.lstat()
            if _linklike(path):
                self.entries[path] = _Entry("link", None)
                continue
            entry_id = (info.st_dev, info.st_ino)
            if stat.S_ISDIR(info.st_mode):
                self.entries[path] = _Entry("dir", entry_id)
                pending.extend(reversed(sorted(path.iterdir(), key=lambda p: (p.name.casefold(), p.name))))
            elif stat.S_ISREG(info.st_mode):
                self.entries[path] = _Entry("file", entry_id)
            else:
                self.entries[path] = _Entry("other", entry_id)

    def check(self, path: Path) -> Path:
        candidate = _absolute(path)
        if candidate != self.root and self.root not in candidate.parents:
            raise UnsafePathError(f"Path outside the selected media folder: {candidate}")
        for item in (candidate, *candidate.parents):
            if self.entries.get(item, _Entry("", None)).kind == "link":
                raise UnsafePathError(f"Refusing link or reparse point: {item}")
            if item == self.root:
                break
        return candidate

    def kind(self, path: Path) -> str:
        return self.entries.get(self.check(path), _Entry("", None)).kind

    def occupied(self, path: Path) -> bool:
        candidate = _absolute(path)
        if candidate == self.root or self.root in candidate.parents:
            return candidate in self.entries
        # Single-folder mode may reserve a new sibling name for the root.
        if self.single and candidate.parent == self.root.parent:
            return candidate in self.entries or os.path.lexists(candidate)
        raise UnsafePathError(f"Path outside the selected media folder: {candidate}")

    def children(self, path: Path) -> list[Path]:
        folder = self.check(path)
        if self.kind(folder) != "dir":
            raise NotADirectoryError(str(folder))
        return sorted(
            (p for p, entry in self.entries.items() if p != folder and p.parent == folder and entry.kind != "link"),
            key=lambda p: (p.name.casefold(), p.name),
        )

    def walk(self, path: Path) -> Iterator[Path]:
        pending = [self.check(path)]
        while pending:
            for child in self.children(pending.pop()):
                yield child
                if self.kind(child) == "dir":
                    pending.append(child)

    def mkdir(self, path: Path) -> None:
        target = self.check(path)
        if self.kind(target) == "dir":
            return
        if self.occupied(target) or self.kind(target.parent) != "dir":
            raise UnsafePathError(f"Cannot create directory: {target}")
        self.entries[target] = _Entry("dir", None)
        self.operations.append(Operation("mkdir", target))

    def rename(self, source: Path, destination: Path) -> None:
        old = self.check(source)
        new = _absolute(destination)
        if old == new:
            return
        root_move = old == self.root
        if root_move:
            if not self.single or new.parent != self.root.parent:
                raise UnsafePathError("The selected root may only be renamed alongside itself.")
        else:
            self.check(new)
            if self.kind(new.parent) != "dir" or old in new.parents:
                raise UnsafePathError(f"Invalid rename destination: {new}")
        entry = self.entries.get(old)
        if entry is None or entry.kind not in {"file", "dir"} or entry.identity is None:
            raise UnsafePathError(f"Cannot rename source: {old}")
        if self.occupied(new):
            raise FileExistsError(str(new))
        # Move the directory and every virtual descendant as a single operation.
        descendants = [p for p in self.entries if p == old or old in p.parents]
        for path in descendants:
            relative = path.relative_to(old)
            self.entries[new / relative] = self.entries.pop(path)
        self.operations.append(Operation("rename", new, old, entry.identity))
        if root_move:
            self.root = new

    def plan(self) -> Plan:
        return Plan(self.initial_root, self.single, tuple(self.operations))


_active: ContextVar[Planner | None] = ContextVar("media_cleanup_planner", default=None)


@contextmanager
def planning(root: Path, *, single: bool = False) -> Iterator[Planner]:
    planner = Planner(root, single=single)
    token = _active.set(planner)
    try:
        yield planner
    finally:
        _active.reset(token)


def _planner() -> Planner:
    value = _active.get()
    if value is None:
        raise RuntimeError("Media organization requires an active planning context.")
    return value


def safe_check(path: Path) -> Path:
    return _planner().check(path)


def safe_children(path: Path) -> list[Path]:
    return _planner().children(path)


def safe_walk(path: Path) -> Iterator[Path]:
    return _planner().walk(path)


def safe_is_dir(path: Path) -> bool:
    return _planner().kind(path) == "dir"


def safe_is_file(path: Path) -> bool:
    return _planner().kind(path) == "file"


def safe_exists(path: Path) -> bool:
    return bool(_planner().kind(path))


def occupied(path: Path) -> bool:
    return _planner().occupied(path)


def safe_mkdir(path: Path) -> None:
    _planner().mkdir(path)


def safe_rename(source: Path, destination: Path) -> None:
    _planner().rename(source, destination)
