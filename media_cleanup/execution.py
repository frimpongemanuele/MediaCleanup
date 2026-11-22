"""Apply an exact plan and keep a durable, reversible operation journal."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from filesystem_safety import FilesystemGuard, UnsafePathError, _absolute, _check_components
from .filesystem import Identity, Operation, Plan, identity


def _external_path(path: Path, root: Path) -> Path:
    path = _absolute(path.expanduser())
    if path == root or root in path.parents:
        raise UnsafePathError("Keep plan and journal files outside the selected media folder.")
    _check_components(path)
    return path


def write_plan(plan: Plan, path: Path) -> Path:
    path = _external_path(path, plan.root)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(plan.to_dict(), handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    return path


def read_plan(path: Path) -> Plan:
    path = _absolute(path.expanduser())
    _check_components(path)
    with path.open(encoding="utf-8") as handle:
        return Plan.from_dict(json.load(handle))


def default_journal(root: Path) -> Path:
    return root.parent / f"media-cleanup-journal-{uuid4().hex}.jsonl"


def _record(handle: TextIO, event: dict) -> None:
    handle.write(json.dumps(event, ensure_ascii=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _destination(guard: FilesystemGuard, source: Path | None, target: Path) -> None:
    if source == guard.root and target != source:
        if not guard.allow_root_rename or target.parent != guard.root.parent:
            raise UnsafePathError("Root rename is outside single-folder scope.")
        _check_components(target)
    else:
        guard.check(target)
    if os.path.lexists(target):
        raise FileExistsError(f"Destination already exists: {target}")
    if not target.parent.is_dir():
        raise NotADirectoryError(str(target.parent))
    if source is not None and source in target.parents:
        raise UnsafePathError("Cannot move a directory inside itself.")


def _require_identity(guard: FilesystemGuard, path: Path, expected: Identity) -> None:
    guard.check(path)
    if identity(path) != expected:
        raise UnsafePathError(f"Path has changed since planning: {path}")


def _perform(guard: FilesystemGuard, operation: Operation, handle: TextIO, index: int) -> None:
    if operation.kind == "rename":
        source, expected = operation.source, operation.source_id
        if source is None or expected is None:
            raise ValueError("Rename requires an original source identity.")
        _require_identity(guard, source, expected)
        _destination(guard, source, operation.target)
        _record(handle, {"event": "pending", "index": index})
        guard.rename(source, operation.target)
    elif operation.kind == "mkdir":
        _destination(guard, None, operation.target)
        _record(handle, {"event": "pending", "index": index})
        # Do not accept directories created after planning.
        guard.check(operation.target).mkdir(exist_ok=False)
    else:
        raise ValueError("Unknown operation.")
    actual = identity(operation.target)
    if operation.kind == "rename" and actual != operation.source_id:
        raise UnsafePathError("Rename result could not be verified.")
    _record(handle, {"event": "done", "index": index, "identity": list(actual)})


def apply_plan(plan: Plan, journal: Path | None = None) -> Path:
    guard = FilesystemGuard(plan.root, allow_root_rename=plan.single)
    path = _external_path(journal or default_journal(plan.root), plan.root)
    # Exclusive creation is deliberate; never replace an existing journal.
    with path.open("x", encoding="utf-8") as handle:
        _record(handle, {"event": "header", "plan": plan.to_dict()})
        print(f"Journal: {path}")
        for index, operation in enumerate(plan.operations):
            _perform(guard, operation, handle, index)
        _record(handle, {"event": "complete"})
    return path


def _read_journal(path: Path) -> tuple[Plan, list[tuple[int, Identity]]]:
    with path.open(encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle]
    if not events or not isinstance(events[0], dict) or events[0].get("event") != "header":
        raise ValueError("Invalid journal header.")
    plan = Plan.from_dict(events[0].get("plan"))
    done: list[tuple[int, Identity]] = []
    next_index = 0
    pending: tuple[str, int] | None = None
    completed = False
    undo_started = False

    for entry in events[1:]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid journal entry.")
        event = entry.get("event")
        index = entry.get("index")
        if event == "complete":
            if pending is not None or completed or undo_started or next_index != len(plan.operations):
                raise ValueError("Invalid journal completion.")
            completed = True
            continue
        if type(index) is not int or not 0 <= index < len(plan.operations):
            raise ValueError("Invalid journal operation index.")
        if event == "pending" and not completed and not undo_started and pending is None and index == next_index:
            pending = ("apply", index)
        elif event == "done" and pending == ("apply", index):
            actual = entry.get("identity")
            if not isinstance(actual, list) or len(actual) != 2 or any(type(n) is not int for n in actual):
                raise ValueError("Invalid journal identity.")
            done.append((index, tuple(actual)))
            next_index += 1
            pending = None
        elif event == "undo_pending" and pending is None and done and index == done[-1][0]:
            undo_started = True
            pending = ("undo", index)
        elif event == "undone" and pending == ("undo", index):
            done.pop()
            pending = None
        else:
            raise ValueError("Invalid journal sequence.")
    if pending is not None:
        raise UnsafePathError("Journal contains an interrupted operation; inspect the media and journal manually before recovery.")
    return plan, done


def _current_root(plan: Plan, completed: list[tuple[int, Identity]]) -> Path:
    root = plan.root
    for index, _ in completed:
        operation = plan.operations[index]
        if operation.kind == "rename" and operation.source == root:
            if not plan.single or operation.target.parent != root.parent:
                raise UnsafePathError("Invalid root rename in journal.")
            root = operation.target
    return root


def rollback(journal: Path, root: Path, *, single: bool = False) -> int:
    """Undo confirmed operations in reverse order; remove only empty created directories."""
    root = _absolute(root.expanduser())
    path = _external_path(journal, root)
    plan, completed = _read_journal(path)
    if plan.root != root or plan.single != single:
        raise UnsafePathError("Journal root or single-folder mode does not match the command.")
    if not completed:
        return 0
    current_root = _current_root(plan, completed)
    _external_path(path, current_root)
    guard = FilesystemGuard(current_root, allow_root_rename=single)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for index, expected in reversed(completed):
            operation = plan.operations[index]
            target = operation.target
            _require_identity(guard, target, expected)
            if operation.kind == "rename":
                source = operation.source
                if source is None:
                    raise ValueError("Invalid rename in journal.")
                _destination(guard, target, source)
                _record(handle, {"event": "undo_pending", "index": index})
                guard.rename(target, source)
            elif operation.kind == "mkdir":
                if not target.is_dir() or any(target.iterdir()):
                    raise UnsafePathError(f"Will not remove a non-empty or changed directory: {target}")
                _record(handle, {"event": "undo_pending", "index": index})
                guard.check(target).rmdir()
            else:
                raise ValueError("Unknown journal operation.")
            _record(handle, {"event": "undone", "index": index})
            count += 1
    return count
