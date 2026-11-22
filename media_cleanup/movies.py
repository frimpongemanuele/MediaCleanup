"""Movie and subtitle organization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Tuple
from collections import defaultdict
from . import tmdb
from .naming import (
    clean_text,
    title_case_safely,
    extract_year,
    extract_version_label,
    detect_language,
    english_to_italian_title,
    guess_title_from_string,
    detect_language_from_tmdb_titles,
    score_title_candidate,
    resolve_numbered_franchise_title,
    build_folder_base_name,
    VIDEO_EXTS,
    SUB_EXTS,
    INFO_EXTS,
    SUBTITLE_LANG_CODES,
)
from .media_files import (
    is_video_file,
    is_sub_file,
    is_info_file,
    unique_path,
    unique_folder_path,
    rename_item,
)
from .filesystem import (
    safe_children,
    safe_walk,
    safe_mkdir,
    safe_rename,
    safe_exists,
    safe_is_dir,
    safe_is_file,
)

def infer_standalone_file_movie(file_path: Path) -> dict:
    local_year = extract_year(file_path.stem)

    candidates: List[str] = []

    franchise_title = resolve_numbered_franchise_title(file_path.name)
    if franchise_title:
        candidates.append(franchise_title)

    en_guess = guess_title_from_string(file_path.name, prefer_language="English")
    it_guess = guess_title_from_string(file_path.name, prefer_language="Italian")

    if en_guess:
        candidates.append(en_guess)
    if it_guess:
        candidates.append(it_guess)

    seen = set()
    deduped = []
    for c in candidates:
        key = clean_text(c).lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(c)

    resolved_title = deduped[0] if deduped else title_case_safely(clean_text(file_path.stem))
    resolved_year = local_year
    tmdb_id = None
    localized_titles = None
    confidence = 0.0

    if tmdb.TMDB_API_KEY and deduped:
        title, year, found_tmdb_id, score = tmdb.resolve_tmdb_match(deduped, fallback_year=local_year)
        if found_tmdb_id and title:
            resolved_title = title
            resolved_year = year or local_year
            tmdb_id = found_tmdb_id
            confidence = score
            localized_titles = tmdb.get_tmdb_localized_titles(found_tmdb_id)

    lang = detect_language(file_path.name)

    if not lang and localized_titles:
        lang = detect_language_from_tmdb_titles(
            file_path.name,
            english_title=localized_titles.get("en", resolved_title),
            italian_title=localized_titles.get("it", resolved_title),
        )

    return {
        "source": file_path,
        "title": resolved_title,
        "year": resolved_year,
        "tmdb_id": tmdb_id,
        "localized_titles": localized_titles,
        "confidence": confidence,
        "language": lang,
    }


def group_standalone_files_by_movie(video_files: List[Path]) -> tuple[dict, list[dict]]:
    grouped = defaultdict(list)
    unresolved = []

    for vf in sorted(video_files, key=lambda p: p.name.lower()):
        info = infer_standalone_file_movie(vf)

        if info["tmdb_id"] and info["confidence"] >= 0.70:
            grouped[info["tmdb_id"]].append(info)
        else:
            unresolved.append(info)

    return grouped, unresolved


def infer_movie_name_and_year(folder: Path) -> Tuple[str, Optional[str], str, Optional[int], Optional[dict]]:
    years: List[str] = []
    english_candidates: List[Tuple[str, int]] = []
    italian_candidates: List[Tuple[str, int]] = []
    video_languages: List[str] = []

    for item in safe_walk(folder):
        if not safe_is_file(item):
            continue

        if item.suffix.lower() not in (VIDEO_EXTS | SUB_EXTS | INFO_EXTS):
            continue

        local_year = extract_year(item.stem)
        if local_year:
            years.append(local_year)

        english_title = guess_title_from_string(item.name, prefer_language="English")
        italian_title = guess_title_from_string(item.name, prefer_language="Italian")

        if english_title:
            english_candidates.append((english_title, score_title_candidate(english_title)))
        if italian_title:
            italian_candidates.append((italian_title, score_title_candidate(italian_title)))

        if item.suffix.lower() in VIDEO_EXTS:
            lang = detect_language(item.name)
            if lang:
                video_languages.append(lang)

    folder_guess_en = guess_title_from_string(folder.name, prefer_language="English")
    folder_guess_it = guess_title_from_string(folder.name, prefer_language="Italian")

    if folder_guess_en:
        english_candidates.append((folder_guess_en, score_title_candidate(folder_guess_en)))
    if folder_guess_it:
        italian_candidates.append((folder_guess_it, score_title_candidate(folder_guess_it)))

    unique_video_langs = sorted(set(video_languages))

    folder_language = "English"
    if unique_video_langs == ["Italian"]:
        folder_language = "Italian"

    if folder_language == "Italian" and italian_candidates:
        best_title = max(italian_candidates, key=lambda x: x[1])[0]
    elif english_candidates:
        best_title = max(english_candidates, key=lambda x: x[1])[0]
    elif italian_candidates:
        best_title = max(italian_candidates, key=lambda x: x[1])[0]
    else:
        best_title = title_case_safely(clean_text(folder.name))

    best_year = sorted(set(years))[0] if years else extract_year(folder.name)
    tmdb_id: Optional[int] = None
    localized_titles: Optional[dict] = None

    combined_candidates: List[str] = []
    for cand, _ in sorted(english_candidates, key=lambda x: x[1], reverse=True):
        combined_candidates.append(cand)
    for cand, _ in sorted(italian_candidates, key=lambda x: x[1], reverse=True):
        combined_candidates.append(cand)
    if best_title:
        combined_candidates.insert(0, best_title)

    if not best_year:
        if not tmdb.TMDB_API_KEY:
            print(f"  [TMDb] Skipped for '{best_title}' because TMDB_API_KEY is missing.")
        else:
            resolved_title, resolved_year, found_tmdb_id, confidence = tmdb.resolve_tmdb_match(combined_candidates)

            if found_tmdb_id and resolved_year and confidence >= 0.70:
                print(f"  [TMDb] Matched '{best_title}' -> '{resolved_title}' ({resolved_year}) [score={confidence:.2f}]")
                best_title = resolved_title
                best_year = resolved_year
                tmdb_id = found_tmdb_id
                localized_titles = tmdb.get_tmdb_localized_titles(found_tmdb_id)
            elif resolved_year:
                print(f"  [REVIEW] Weak TMDb match for '{best_title}' -> '{resolved_title}' ({resolved_year}) [score={confidence:.2f}]")
            else:
                print(f"  [TMDb] No confident year found for '{best_title}'")

    if not localized_titles and tmdb.TMDB_API_KEY and best_title and best_year:
        resolved_title, resolved_year, found_tmdb_id, confidence = tmdb.resolve_tmdb_match(combined_candidates, fallback_year=best_year)
        if found_tmdb_id and confidence >= 0.70:
            tmdb_id = found_tmdb_id
            localized_titles = tmdb.get_tmdb_localized_titles(found_tmdb_id)

    return best_title, best_year, folder_language, tmdb_id, localized_titles


def process_movie_folder(folder: Path) -> None:
    print(f"\n=== {folder}")

    title, year, folder_language, tmdb_id, localized_titles = infer_movie_name_and_year(folder)

    source_dir = folder
    subdirs = [p for p in safe_children(folder) if safe_is_dir(p)]
    files_here = [p for p in safe_children(folder) if safe_is_file(p)]
    if len(subdirs) == 1 and not files_here:
        source_dir = subdirs[0]
        print(f"  Using nested source folder: {source_dir.name}")

    all_items = list(safe_children(source_dir))

    video_files = [p for p in all_items if is_video_file(p)]
    sub_files = [p for p in all_items if is_sub_file(p)]
    info_files = [p for p in all_items if is_info_file(p)]

    if not video_files and not sub_files and not info_files:
        print("  [SKIP] No relevant media files found.")
        return

    lang_seen = {}

    sorted_video_files = sorted(video_files, key=lambda p: p.name.lower())
    resolved_lang_map = {
        vf: resolve_video_language(vf, title, localized_titles)
        for vf in sorted_video_files
    }
    detected_video_langs: List[Optional[str]] = [resolved_lang_map[vf] for vf in sorted_video_files]

    for vf in sorted_video_files:
        lang = resolved_lang_map[vf]

        if lang == "Italian":
            if localized_titles and localized_titles.get("it"):
                video_title = localized_titles["it"]
            else:
                guessed_video_title = guess_title_from_string(vf.name, prefer_language="Italian")
                video_title = guessed_video_title or english_to_italian_title(title)
        else:
            if localized_titles and localized_titles.get("en"):
                video_title = localized_titles["en"]
            else:
                guessed_video_title = guess_title_from_string(vf.name, prefer_language="English")
                video_title = guessed_video_title or title

        video_base_name = build_folder_base_name(video_title, year)

        version_label = extract_version_label(vf.name)

        if not lang:
            if len(video_files) == 1:
                new_name = f"{video_base_name}{vf.suffix.lower()}"
            else:
                if version_label:
                    new_name = f"{video_base_name} - {version_label}{vf.suffix.lower()}"
                else:
                    idx = lang_seen.get("Version", 0) + 1
                    lang_seen["Version"] = idx
                    new_name = f"{video_base_name} - Version {idx}{vf.suffix.lower()}"
        else:
            same_lang_files = [p for p in sorted_video_files if resolved_lang_map[p] == lang]
            count = lang_seen.get(lang, 0) + 1
            lang_seen[lang] = count

            if len(same_lang_files) > 1:
                if version_label:
                    suffix = f" - {lang} - {version_label}"
                else:
                    suffix = f" - {lang} {count}"
            else:
                suffix = f" - {lang}"

            new_name = f"{video_base_name}{suffix}{vf.suffix.lower()}"

        rename_item(vf, source_dir / new_name)

    unique_detected_video_langs = sorted(set(x for x in detected_video_langs if x))

    if unique_detected_video_langs == ["Italian"]:
        if localized_titles and localized_titles.get("it"):
            title = localized_titles["it"]
    else:
        if localized_titles and localized_titles.get("en"):
            title = localized_titles["en"]

    file_base_name = build_folder_base_name(title, year)
    base_name_folder = build_folder_base_name(title, year, tmdb_id)
    video_languages = detected_video_langs[:]

    for sf in sorted(sub_files, key=lambda p: p.name.lower()):
        lang = detect_language(sf.name)

        if not lang:
            known_langs = [x for x in video_languages if x]
            unique_known = sorted(set(known_langs))
            if len(unique_known) == 1:
                lang = unique_known[0]

        if lang and lang in SUBTITLE_LANG_CODES:
            code = SUBTITLE_LANG_CODES[lang]
            new_name = f"{file_base_name}.{code}{sf.suffix.lower()}"
        else:
            new_name = f"{file_base_name}{sf.suffix.lower()}"

        rename_item(sf, source_dir / new_name)

    for nf in sorted(info_files, key=lambda p: p.name.lower()):
        new_name = f"{file_base_name}{nf.suffix.lower()}"
        rename_item(nf, source_dir / new_name)

    final_folder_path = folder.parent / base_name_folder
    current_main_folder = folder

    if current_main_folder.name != base_name_folder:
        print(f"  Folder {current_main_folder.name}  ->  {base_name_folder}")
        safe_rename(current_main_folder, unique_folder_path(final_folder_path))
        current_main_folder = final_folder_path

    if source_dir != folder:
        print("  [NOTE] Nested subfolder detected. After checking results, you may want to move files up one level and remove the extra inner folder manually.")


def resolve_video_language(
    file_path: Path,
    fallback_title: str,
    localized_titles: Optional[dict]
) -> Optional[str]:
    """
    Resolve language using:
    1. direct filename heuristics
    2. TMDb localized title comparison
    """
    lang = detect_language(file_path.name)

    if not lang and localized_titles:
        lang = detect_language_from_tmdb_titles(
            file_path.name,
            english_title=localized_titles.get("en", fallback_title),
            italian_title=localized_titles.get("it", fallback_title),
        )

    return lang


def split_multi_movie_folder(folder: Path) -> bool:
    if not safe_exists(folder) or not safe_is_dir(folder):
        print(f"  [SKIP] Folder does not exist: {folder}")
        return False
    
    all_items = list(safe_children(folder))
    video_files = [p for p in all_items if is_video_file(p)]
    subdirs = [p for p in all_items if safe_is_dir(p)]

    if len(video_files) <= 1 or subdirs:
        return False

    print(f"\n=== {folder}")
    print("  [MULTI] Detected multiple standalone video files in one folder")

    grouped, unresolved = group_standalone_files_by_movie(video_files)

    for tmdb_id, items in grouped.items():
        first = items[0]
        localized_titles = first.get("localized_titles") or {}
        year = first.get("year")
        folder_title = localized_titles.get("en") or first["title"]
        folder_name = build_folder_base_name(folder_title, year, tmdb_id)

        print(f"  [GROUP] tmdb_id={tmdb_id} -> {folder_name}")

        lang_seen = {}

        for info in items:
            src = info["source"]
            lang = info.get("language")

            if lang == "Italian":
                file_title = localized_titles.get("it") or english_to_italian_title(folder_title)
            else:
                file_title = localized_titles.get("en") or folder_title

            file_base = build_folder_base_name(file_title, year)

            version_label = extract_version_label(src.name)

            if not lang:
                if len(items) == 1:
                    new_name = f"{file_base}{src.suffix.lower()}"
                else:
                    if version_label:
                        new_name = f"{file_base} - {version_label}{src.suffix.lower()}"
                    else:
                        idx = lang_seen.get("Version", 0) + 1
                        lang_seen["Version"] = idx
                        new_name = f"{file_base} - Version {idx}{src.suffix.lower()}"
            else:
                count = lang_seen.get(lang, 0) + 1
                lang_seen[lang] = count

                # If there are multiple files with same language, prefer version labels
                if count == 1:
                    suffix = f" - {lang}"
                else:
                    if version_label:
                        suffix = f" - {lang} - {version_label}"
                    else:
                        suffix = f" - {lang} {count}"

                # Also if first file has a version label and there are multiple same-language files,
                # label it too for consistency
                if count == 1 and len([x for x in items if x.get('language') == lang]) > 1 and version_label:
                    suffix = f" - {lang} - {version_label}"

                new_name = f"{file_base}{suffix}{src.suffix.lower()}"

            target_folder = folder / folder_name
            target_file = target_folder / new_name

            print(f"  Move file    : {src.name} -> {folder_name}\\{new_name}")

            safe_mkdir(target_folder)
            safe_rename(src, unique_path(target_file))

    if unresolved:
        review_folder = folder / "_Needs_Review"
        for info in unresolved:
            src = info["source"]
            print(f"  [REVIEW] {src.name}")
            safe_mkdir(review_folder)
            safe_rename(src, unique_path(review_folder / src.name))

    return True
