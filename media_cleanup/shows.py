"""TV series and episode organization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Tuple
import re
from . import tmdb
from .naming import (
    clean_text,
    title_case_safely,
    has_episode_pattern,
    strip_junk,
    build_folder_base_name,
    is_season_folder_name,
    extract_season_number_from_folder,
    extract_episode_number,
    extract_season_number_from_filename,
    infer_series_name_from_folder,
)
from .media_files import (
    is_video_file,
    unique_folder_path,
    rename_item,
)
from .filesystem import (
    safe_children,
    safe_mkdir,
    safe_rename,
    safe_is_dir,
)

def detect_flat_show_folder(folder: Path) -> bool:
    """
    A folder is considered a flat show folder if it contains
    multiple video files with episode patterns directly inside it.
    """
    if not safe_is_dir(folder):
        return False

    video_files = [p for p in safe_children(folder) if is_video_file(p)]
    if len(video_files) < 2:
        return False

    episode_like = sum(1 for vf in video_files if has_episode_pattern(vf.name))
    return episode_like >= 2


def detect_show_root(folder: Path) -> bool:
    """
    A folder is considered a show root if it contains at least one season-like subfolder.
    Example:
      Assassination_Classroom/
        Season_1/
        Season_2/
    """
    if not safe_is_dir(folder):
        return False

    for item in safe_children(folder):
        if safe_is_dir(item) and is_season_folder_name(item.name):
            return True
    return False


def rename_show_episode_file(
    file_path: Path,
    series_title: str,
    season_num: int,
    episode_num: int,
) -> Path:
    new_name = f"{clean_text(series_title)} S{season_num:02d}E{episode_num:02d}{file_path.suffix.lower()}"
    return rename_item(file_path, file_path.parent / new_name)


def infer_show_identity(show_root: Path) -> Tuple[str, Optional[str], Optional[int], Optional[dict]]:
    """
    Resolve the show root against TMDb TV.
    Returns:
      (series_title, year, tmdb_id, localized_titles)
    """
    local_guess = infer_series_name_from_folder(show_root)
    candidates: List[str] = [local_guess]

    fallback = title_case_safely(clean_text(show_root.name))
    if fallback and clean_text(fallback).lower() != clean_text(local_guess).lower():
        candidates.append(fallback)

    # If folder has season subfolders, sample from them
    season_dirs = sorted(
        [p for p in safe_children(show_root) if safe_is_dir(p) and is_season_folder_name(p.name)],
        key=lambda p: p.name.lower()
    )

    for season_dir in season_dirs[:2]:
        episode_files = sorted(
            [p for p in safe_children(season_dir) if is_video_file(p)],
            key=lambda p: p.name.lower()
        )[:3]

        for ep_file in episode_files:
            stem = strip_junk(ep_file.stem)
            stem = re.sub(r"\bS\d{1,2}E\d{1,3}\b", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"\b\d{1,2}x\d{1,3}\b", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"\bs\d+\b", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"\bep(?:isode)?\b", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"\(\s*\d+\s*\)", "", stem)
            stem = re.sub(r"\b\d{1,3}\b", "", stem)
            stem = re.sub(r"\bdual audio\b", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"\s+", " ", stem).strip()

            if stem:
                candidates.append(title_case_safely(stem))

    # If folder is flat, sample episode files directly
    flat_episode_files = sorted(
        [p for p in safe_children(show_root) if is_video_file(p)],
        key=lambda p: p.name.lower()
    )[:5]

    for ep_file in flat_episode_files:
        stem = strip_junk(ep_file.stem)
        stem = re.sub(r"\bS\d{1,2}E\d{1,3}\b", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"\b\d{1,2}x\d{1,3}\b", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"\bs\d+\b", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"\bep(?:isode)?\b", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"\(\s*\d+\s*\)", "", stem)
        stem = re.sub(r"\b\d{1,3}\b", "", stem)
        stem = re.sub(r"\bdual audio\b", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"\s+", " ", stem).strip()

        if stem:
            candidates.append(title_case_safely(stem))

    seen = set()
    deduped = []
    for c in candidates:
        key = clean_text(c).lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(c)

    resolved_name = local_guess
    resolved_year = None
    tmdb_id = None
    localized_titles = None

    if tmdb.TMDB_API_KEY:
        title, year, found_tmdb_id, confidence = tmdb.resolve_tmdb_tv_match(deduped)
        if found_tmdb_id and title and confidence >= 0.60:
            print(f"  [TMDb TV] Matched '{local_guess}' -> '{title}' ({year}) [score={confidence:.2f}]")
            resolved_name = title
            resolved_year = year
            tmdb_id = found_tmdb_id
            localized_titles = tmdb.get_tmdb_tv_localized_titles(found_tmdb_id)
        elif title:
            print(f"  [REVIEW] Weak TMDb TV match for '{local_guess}' -> '{title}' ({year}) [score={confidence:.2f}]")

    return resolved_name, resolved_year, tmdb_id, localized_titles


def process_show_folder(show_root: Path) -> None:
    """
    Process a TV show folder structured like:
      Show Name/
        Season_1/
        Season_2/
    Renames into Jellyfin-friendly structure.
    """
    print(f"\n=== {show_root}")
    print("  [SHOW] Detected TV series structure")

    series_title, series_year, tmdb_id, localized_titles = infer_show_identity(show_root)

    print(f"  DEBUG show match -> title={series_title}, year={series_year}, tmdb_id={tmdb_id}")

    # Prefer English canonical title for the root folder
    if localized_titles and localized_titles.get("en"):
        series_title = localized_titles["en"]

    desired_root_name = build_folder_base_name(series_title, series_year, tmdb_id)

    if show_root.name != desired_root_name:
        print(f"  Show folder {show_root.name}  ->  {desired_root_name}")
        target = unique_folder_path(show_root.parent / desired_root_name)
        safe_rename(show_root, target)
        show_root = target

    season_dirs = sorted(
        [p for p in safe_children(show_root) if safe_is_dir(p) and is_season_folder_name(p.name)],
        key=lambda p: p.name.lower()
    )

    if not season_dirs:
        print("  [SKIP] No season folders found.")
        return

    for season_dir in season_dirs:
        season_num = extract_season_number_from_folder(season_dir.name)
        if season_num is None:
            print(f"  [SKIP] Could not determine season number from folder: {season_dir.name}")
            continue

        normalized_season_name = f"Season {season_num:02d}"
        if season_dir.name != normalized_season_name:
            print(f"  Season folder {season_dir.name}  ->  {normalized_season_name}")
            target = unique_folder_path(season_dir.parent / normalized_season_name)
            safe_rename(season_dir, target)
            season_dir = target

        episode_files = sorted(
            [p for p in safe_children(season_dir) if is_video_file(p)],
            key=lambda p: (extract_episode_number(p.name) or 999, p.name.lower())
        )

        if not episode_files:
            print(f"  [SKIP] No episode files in {season_dir.name}")
            continue

        for ep_file in episode_files:
            ep_num = extract_episode_number(ep_file.name)
            if ep_num is None:
                print(f"  [REVIEW] Could not extract episode number: {ep_file.name}")
                continue

            new_name = clean_text(series_title)
            if series_year:
                new_name += f" ({series_year})"
            new_name += f" S{season_num:02d}E{ep_num:02d}{ep_file.suffix.lower()}"

            rename_item(ep_file, ep_file.parent / new_name)


def process_flat_show_folder(show_root: Path) -> None:
    """
    Process a flat TV show folder like:
      Show/
        Show.S01E01.mkv
        Show.S01E02.mkv
        Show.S01E03.mkv

    It will:
    - resolve the show identity
    - rename the root folder
    - create Season XX folders
    - move/rename episodes into Jellyfin format
    """
    print(f"\n=== {show_root}")
    print("  [SHOW-FLAT] Detected flat TV series structure")

    series_title, series_year, tmdb_id, localized_titles = infer_show_identity(show_root)
    print(f"  DEBUG show match -> title={series_title}, year={series_year}, tmdb_id={tmdb_id}")

    if localized_titles and localized_titles.get("en"):
        series_title = localized_titles["en"]

    desired_root_name = build_folder_base_name(series_title, series_year, tmdb_id)

    if show_root.name != desired_root_name:
        print(f"  Show folder {show_root.name}  ->  {desired_root_name}")
        target = unique_folder_path(show_root.parent / desired_root_name)
        safe_rename(show_root, target)
        show_root = target

    episode_files = sorted(
        [p for p in safe_children(show_root) if is_video_file(p)],
        key=lambda p: (
            extract_season_number_from_filename(p.name) or 999,
            extract_episode_number(p.name) or 999,
            p.name.lower()
        )
    )

    for ep_file in episode_files:
        season_num = extract_season_number_from_filename(ep_file.name)
        episode_num = extract_episode_number(ep_file.name)

        if season_num is None or episode_num is None:
            print(f"  [REVIEW] Could not extract S/E from: {ep_file.name}")
            continue

        season_folder_name = f"Season {season_num:02d}"
        target_season_dir = show_root / season_folder_name
        new_name = clean_text(series_title)
        if series_year:
            new_name += f" ({series_year})"
        new_name += f" S{season_num:02d}E{episode_num:02d}{ep_file.suffix.lower()}"

        print(f"  Episode folder -> {season_folder_name}")
        print(f"  {ep_file.name}  ->  {new_name}")

        safe_mkdir(target_season_dir)
        rename_item(ep_file, target_season_dir / new_name)
