"""Batch selection and media routing."""

from __future__ import annotations

from pathlib import Path
from typing import List
from .media_files import (
    unique_folder_path,
)
from .movies import (
    process_movie_folder,
    split_multi_movie_folder,
)
from .shows import (
    detect_flat_show_folder,
    detect_show_root,
    process_show_folder,
    process_flat_show_folder,
)
from .filesystem import (
    safe_children,
    safe_mkdir,
    safe_rename,
    safe_is_dir,
)

MOVIES_DIRNAME = "0_Movies"

SHOWS_DIRNAME = "0_Shows"


def is_reserved_library_folder(path: Path) -> bool:
    return path.name.lower() in {MOVIES_DIRNAME.lower(), SHOWS_DIRNAME.lower()}


def get_media_subfolders(root: Path) -> List[Path]:
    """
    Return top-level folders in the media root, excluding reserved library folders.
    """
    folders = []
    for item in sorted(safe_children(root), key=lambda p: p.name.lower()):
        if not safe_is_dir(item):
            continue
        if is_reserved_library_folder(item):
            continue
        folders.append(item)
    return folders


def ensure_library_dirs(root: Path) -> tuple[Path, Path]:
    movies_dir = root / MOVIES_DIRNAME
    shows_dir = root / SHOWS_DIRNAME

    safe_mkdir(movies_dir)
    safe_mkdir(shows_dir)

    return movies_dir, shows_dir


def move_folder_to_library(folder: Path, library_dir: Path) -> Path:
    """
    Move a top-level folder into the target library directory.
    Record the move in the plan and return its virtual destination.
    """
    target = library_dir / folder.name

    if folder.parent == library_dir:
        return folder

    final_target = unique_folder_path(target)

    print(f"  Library move {folder}  ->  {final_target}")

    safe_rename(folder, final_target)
    return final_target



def process_entry_with_library_routing(entry: Path, media_root: Path) -> None:
    """
    Route a top-level media folder into 0_Movies or 0_Shows, then process it.
    """
    movies_dir, shows_dir = ensure_library_dirs(media_root)

    if detect_show_root(entry) or detect_flat_show_folder(entry):
        routed_entry = move_folder_to_library(entry, shows_dir)

        if detect_show_root(routed_entry):
            process_show_folder(routed_entry)
        else:
            process_flat_show_folder(routed_entry)
    else:
        routed_entry = move_folder_to_library(entry, movies_dir)

        handled = split_multi_movie_folder(routed_entry)
        if not handled:
            process_movie_folder(routed_entry)
