# execution
# python C:\Users\Emanuele\Documents\Scripts\movie_cleanup.py "H:\Media" --batch-start 0 --batch-size 20
# python C:\Users\Emanuele\Documents\Scripts\movie_cleanup.py "H:\Media" --batch-start 0 --batch-size 20 --apply

# More secure way
# python ... "H:\Media" --batch-start 0 --batch-size 20
# python ... "H:\Media" --batch-start 0 --batch-size 20 --apply

from __future__ import annotations

import argparse
import re
import os
from collections import defaultdict
import requests
from pathlib import Path
from typing import Optional, List, Tuple
from difflib import SequenceMatcher

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_DETAILS_URL = "https://api.themoviedb.org/3/movie/{movie_id}"
TMDB_TV_SEARCH_URL = "https://api.themoviedb.org/3/search/tv"
TMDB_TV_DETAILS_URL = "https://api.themoviedb.org/3/tv/{series_id}"

MOVIES_DIRNAME = "0_Movies"
SHOWS_DIRNAME = "0_Shows"

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".ts", ".m2ts"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
INFO_EXTS = {".nfo"}

FORBIDDEN_CHARS = r'[<>"/\?*\\|]'

SUBTITLE_LANG_CODES = {
    "Italian": "it",
    "English": "en",
}

EN_TO_IT_TITLE_ALIASES = {
    "a quiet place": "Un Posto Tranquillo",
    "the hangover": "Una Notte da Leoni",
    "the hangover part ii": "Una Notte da Leoni 2",
    "the hangover part iii": "Una Notte da Leoni 3",
}

IT_TO_EN_TITLE_ALIASES = {
    "un posto tranquillo": "A Quiet Place",
    "una notte da leoni": "The Hangover",
    "una notte da leoni 2": "The Hangover Part II",
    "una notte da leoni 3": "The Hangover Part III",
}

FRANCHISE_NUMBERED_ALIASES = {
    "after": {
        "1": "After",
        "2": "After We Collided",
        "3": "After We Fell",
        "4": "After Ever Happy",
        "5": "After Everything",
    },
}

def clean_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s*:\s*", " - ", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(FORBIDDEN_CHARS, "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, clean_text(a).lower(), clean_text(b).lower()).ratio()

def title_case_safely(title: str) -> str:
    small_words = {
        "a", "an", "and", "as", "at", "but", "by", "for", "in",
        "nor", "of", "on", "or", "per", "the", "to", "vs", "via"
    }
    words = title.split()
    if not words:
        return title

    out = []
    for i, w in enumerate(words):
        wl = w.lower()
        if i not in (0, len(words) - 1) and wl in small_words:
            out.append(wl)
        elif w.isupper() and len(w) <= 4:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)

def extract_year(text: str) -> Optional[str]:
    m = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", text)
    return m.group(1) if m else None

def remove_year(text: str) -> str:
    text = re.sub(r"\((19\d{2}|20\d{2}|21\d{2})\)", "", text)
    text = re.sub(r"\b(19\d{2}|20\d{2}|21\d{2})\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def search_tmdb_movie(title: str, year: Optional[str] = None, language: str = "en-US") -> Optional[dict]:
    if not TMDB_API_KEY:
        return None

    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": language,
    }
    if year:
        params["year"] = year

    try:
        resp = requests.get(TMDB_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [TMDb] Search failed for '{title}': {e}")
        return None

    results = data.get("results", [])
    if not results:
        return None

    best = None
    best_score = -1.0
    query_clean = clean_text(title).lower()

    for item in results[:10]:
        cand_title = (item.get("title") or "").strip()
        cand_original = (item.get("original_title") or "").strip()

        score_title = similarity(query_clean, cand_title) if cand_title else 0.0
        score_original = similarity(query_clean, cand_original) if cand_original else 0.0
        score = max(score_title, score_original)

        release_date = item.get("release_date") or ""
        cand_year = release_date[:4] if len(release_date) >= 4 else None
        if year and cand_year == year:
            score += 0.15

        if cand_title and clean_text(cand_title).lower() in query_clean:
            score += 0.10
        if cand_original and clean_text(cand_original).lower() in query_clean:
            score += 0.10

        if score > best_score:
            best = item
            best_score = score

    if best is not None:
        best["_match_score"] = best_score

    return best

def get_tmdb_localized_titles(movie_id: int) -> dict:
    if not TMDB_API_KEY:
        return {}

    url = TMDB_DETAILS_URL.format(movie_id=movie_id)
    params = {
        "api_key": TMDB_API_KEY,
        "append_to_response": "translations"
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        en_title = (data.get("title") or "").strip()
        original_title = (data.get("original_title") or "").strip()
        it_title = en_title

        translations = data.get("translations", {}).get("translations", [])
        for trans in translations:
            if trans.get("iso_639_1") == "it":
                it_title = (trans.get("data", {}).get("title") or it_title).strip()
                break

        return {
            "en": en_title or original_title,
            "it": it_title or en_title or original_title,
            "original": original_title or en_title or it_title,
        }
    except Exception as e:
        print(f"  [TMDb] Combined details failed for movie_id={movie_id}: {e}")
        return {}

def search_tmdb_tv(title: str, language: str = "en-US") -> Optional[dict]:
    if not TMDB_API_KEY:
        return None

    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": language,
    }

    try:
        resp = requests.get(TMDB_TV_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [TMDb TV] Search failed for '{title}': {e}")
        return None

    results = data.get("results", [])
    if not results:
        return None

    best = None
    best_score = -1.0
    query_clean = clean_text(title).lower()

    for item in results[:10]:
        cand_name = (item.get("name") or "").strip()
        cand_original = (item.get("original_name") or "").strip()

        score_name = similarity(query_clean, cand_name) if cand_name else 0.0
        score_original = similarity(query_clean, cand_original) if cand_original else 0.0
        score = max(score_name, score_original)

        if cand_name and clean_text(cand_name).lower() in query_clean:
            score += 0.10
        if cand_original and clean_text(cand_original).lower() in query_clean:
            score += 0.10

        if score > best_score:
            best = item
            best_score = score

    if best is not None:
        best["_match_score"] = best_score

    return best

def resolve_tmdb_tv_match(candidate_titles: List[str]) -> Tuple[Optional[str], Optional[str], Optional[int], float]:
    """
    Returns:
      (resolved_name, first_air_year, tmdb_id, confidence)
    """
    if not TMDB_API_KEY:
        return None, None, None, 0.0

    seen = set()
    ordered = []

    for title in candidate_titles:
        variants = {
            title,
            clean_text(title),
            title_case_safely(clean_text(title)),
        }

        for variant in variants:
            key = clean_text(variant).lower()
            if key and key not in seen:
                seen.add(key)
                ordered.append(variant)

    best_result = None
    best_score = -1.0

    for cand_title in ordered[:12]:
        for lang in ("en-US", "it-IT"):
            result = search_tmdb_tv(cand_title, language=lang)
            if not result:
                continue

            score = float(result.get("_match_score", 0.0))
            if score > best_score:
                best_score = score
                best_result = result

    if not best_result:
        return None, None, None, 0.0

    first_air_date = best_result.get("first_air_date") or ""
    resolved_year = first_air_date[:4] if len(first_air_date) >= 4 else None
    resolved_name = best_result.get("name") or best_result.get("original_name")
    tmdb_id = best_result.get("id")

    return resolved_name, resolved_year, tmdb_id, best_score

def get_tmdb_tv_localized_titles(series_id: int) -> dict:
    """
    Returns:
    {
        "en": "...",
        "it": "...",
        "original": "...",
        "year": "2015"
    }
    """
    if not TMDB_API_KEY:
        return {}

    url = TMDB_TV_DETAILS_URL.format(series_id=series_id)
    params = {
        "api_key": TMDB_API_KEY,
        "append_to_response": "translations"
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        en_name = (data.get("name") or "").strip()
        original_name = (data.get("original_name") or "").strip()
        first_air_date = data.get("first_air_date") or ""
        year = first_air_date[:4] if len(first_air_date) >= 4 else None

        it_name = en_name
        translations = data.get("translations", {}).get("translations", [])
        for trans in translations:
            if trans.get("iso_639_1") == "it":
                it_name = (trans.get("data", {}).get("name") or it_name).strip()
                break

        return {
            "en": en_name or original_name,
            "it": it_name or en_name or original_name,
            "original": original_name or en_name or it_name,
            "year": year,
        }
    except Exception as e:
        print(f"  [TMDb TV] Combined details failed for series_id={series_id}: {e}")
        return {}

def extract_version_label(filename: str) -> Optional[str]:
    """
    Extract a meaningful version label from a movie filename.
    Examples:
      1080p
      720p
      2160p
      WEBRip
      BluRay
      1080p WEBRip
    """
    stem = Path(filename).stem
    low = stem.lower()

    parts = []

    # Resolution
    m = re.search(r"\b(2160p|1080p|720p|480p)\b", low, flags=re.IGNORECASE)
    if m:
        parts.append(m.group(1))

    # Source
    source_patterns = [
        ("webrip", "WEBRip"),
        ("web-dl", "WEB-DL"),
        ("bluray", "BluRay"),
        ("brrip", "BRRip"),
        ("hdtv", "HDTV"),
        ("remux", "REMUX"),
    ]

    for raw, label in source_patterns:
        if raw in low:
            parts.append(label)
            break

    if parts:
        return " ".join(parts)

    return None

def fetch_year_from_tmdb(title: str, fallback_year: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[int], float]:
    result = search_tmdb_movie(title, year=fallback_year, language="en-US")
    if not result:
        return None, None, None, 0.0

    release_date = result.get("release_date") or ""
    resolved_year = release_date[:4] if len(release_date) >= 4 else None
    resolved_title = result.get("title") or result.get("original_title") or title
    tmdb_id = result.get("id")
    confidence = float(result.get("_match_score", 0.0))

    return resolved_title, resolved_year, tmdb_id, confidence

def resolve_tmdb_match(candidate_titles: List[str], fallback_year: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[int], float]:
    if not TMDB_API_KEY:
        return None, None, None, 0.0

    seen = set()
    ordered = []
    for title in candidate_titles:
        key = clean_text(title).lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(title)

    best_result = None
    best_score = -1.0

    for cand_title in ordered[:8]:
        result = search_tmdb_movie(cand_title, year=fallback_year, language="en-US")
        if not result:
            continue

        score = float(result.get("_match_score", 0.0))
        if score > best_score:
            best_score = score
            best_result = result

    if not best_result:
        return None, None, None, 0.0

    release_date = best_result.get("release_date") or ""
    resolved_year = release_date[:4] if len(release_date) >= 4 else None
    resolved_title = best_result.get("title") or best_result.get("original_title")
    tmdb_id = best_result.get("id")

    return resolved_title, resolved_year, tmdb_id, best_score

def has_episode_pattern(name: str) -> bool:
    """
    Detect common TV episode markers like:
      S01E01
      s1e2
      1x03
    """
    stem = Path(name).stem
    return (
        re.search(r"\bS\d{1,2}E\d{1,3}\b", stem, flags=re.IGNORECASE) is not None
        or re.search(r"\b\d{1,2}x\d{1,3}\b", stem, flags=re.IGNORECASE) is not None
    )

def detect_flat_show_folder(folder: Path) -> bool:
    """
    A folder is considered a flat show folder if it contains
    multiple video files with episode patterns directly inside it.
    """
    if not folder.is_dir():
        return False

    video_files = [p for p in folder.iterdir() if is_video_file(p)]
    if len(video_files) < 2:
        return False

    episode_like = sum(1 for vf in video_files if has_episode_pattern(vf.name))
    return episode_like >= 2

def detect_language(name: str) -> Optional[str]:
    low = clean_text(name).lower()

    italian_patterns = [
        r"\bita\b",
        r"\bitalian\b",
        r"\bitaliano\b",
        r"\bsubita\b",
        r"\bdoppiato\b",
        r"\beng?sub[ _-]?ita\b",
        r"\bcinefilandia\b",
        r"\bnapoli\b",
    ]

    english_patterns = [
        r"\ben\b",
        r"\beng\b",
        r"\benglish\b",
        r"\binglese\b",
        r"\bsubeng\b",
        r"\boriginal\b",
        r"\bhollywood\b",
        r"\bottplex\b",
    ]

    for pat in italian_patterns:
        if re.search(pat, low):
            return "Italian"

    for pat in english_patterns:
        if re.search(pat, low):
            return "English"

    italian_title = contains_known_italian_title(name)
    english_title = contains_known_english_title(name)

    if italian_title and not english_title:
        return "Italian"
    if english_title and not italian_title:
        return "English"

    return None

def strip_junk(name: str) -> str:
    result = Path(name).stem
    result = clean_text(result)

    # Remove any square-bracketed chunk first, e.g. [YTS.MX], [RARBG], [1080p]
    result = re.sub(r"\[[^\]]*\]", "", result)

    junk_patterns = [
        r"@[\w.-]+",

        # quality / source / codec
        r"\b720p\b", r"\b1080p\b", r"\b2160p\b", r"\b4k\b",
        r"\bbluray\b", r"\bbrrip\b", r"\bwebrip\b", r"\bweb[- ]dl\b",
        r"\bhdtv\b", r"\bremux\b", r"\bhevc\b", r"\bx265\b", r"\bx264\b",
        r"\bh264\b", r"\bh265\b",
        r"\bdd5[ .]?1\b", r"\bddp5[ .]?1\b", r"\baac\b", r"\bac3\b",

        # release groups / site tags
        r"\bfgt\b", r"\byify\b", r"\byts\b", r"\bytsmx\b", r"\byts mx\b",
        r"\brarbg\b", r"\bgalaxytv\b", r"\bxen0n\b",
        r"\borg\b", r"\bproper\b", r"\brepack\b",
        r"\bhollywood\b", r"\bmovie\b", r"\bottplex\b", r"\bcinefilandia\b",
        r"\btruehd\b", r"\batmos\b", r"\b10bit\b", r"\b6ch\b",
        r"\bnetflixxe\b", r"\bnetflix\b",
    ]

    for pat in junk_patterns:
        result = re.sub(pat, "", result, flags=re.IGNORECASE)

    # remove bracketed numeric ids like (7400516)
    result = re.sub(r"\(\d+\)", "", result)

    # remove isolated technical leftovers
    result = re.sub(r"\b(dd|web|dl|hevc|x26[45]|h26[45])\b", "", result, flags=re.IGNORECASE)

    # remove dangling punctuation left behind
    result = re.sub(r"[\[\]\(\)\-–—_]+$", "", result)
    result = re.sub(r"^[\[\]\(\)\-–—_]+", "", result)
    result = re.sub(r"\s*[-–—]\s*$", "", result)
    result = re.sub(r"\s*[-–—]\s*", " ", result)

    # remove stray trailing connector words
    result = re.sub(r"\b(by|from|upload|uploaded)\b$", "", result, flags=re.IGNORECASE)

    result = re.sub(r"\s+", " ", result).strip()
    return result

def contains_known_italian_title(name: str) -> Optional[str]:
    low = clean_text(name).lower()
    for title in IT_TO_EN_TITLE_ALIASES.keys():
        if title in low:
            return title_case_safely(title)
    return None


def contains_known_english_title(name: str) -> Optional[str]:
    low = clean_text(name).lower()
    for title in EN_TO_IT_TITLE_ALIASES.keys():
        if title in low:
            return title_case_safely(title)
    return None


def italian_to_english_title(title: str) -> str:
    low = clean_text(title).lower()
    return IT_TO_EN_TITLE_ALIASES.get(low, title)


def english_to_italian_title(title: str) -> str:
    low = clean_text(title).lower()
    return EN_TO_IT_TITLE_ALIASES.get(low, title)


def guess_title_from_string(name: str, prefer_language: str = "English") -> str:
    raw_name = Path(name).stem

    italian_hint = contains_known_italian_title(raw_name)
    english_hint = contains_known_english_title(raw_name)

    if prefer_language == "Italian" and italian_hint:
        return italian_hint

    if prefer_language == "English":
        if english_hint:
            return english_hint
        if italian_hint:
            return italian_to_english_title(italian_hint)

    name = strip_junk(raw_name)
    name = re.sub(r"\b(19\d{2}|20\d{2}|21\d{2})\b", "", name)
    name = re.sub(r"\b(by|from|upload|uploaded)\b$", "", name, flags=re.IGNORECASE)
    name = clean_text(name)
    name = re.sub(r"\s+", " ", name).strip()
    name = title_case_safely(name)

    if prefer_language == "English":
        name = italian_to_english_title(name)
    elif prefer_language == "Italian":
        name = english_to_italian_title(name)

    return name


def normalize_title_for_match(name: str) -> str:
    text = Path(name).stem
    text = strip_junk(text)
    text = remove_year(text)
    text = clean_text(text)
    return text.lower().strip()


def detect_language_from_tmdb_titles(filename: str, english_title: str, italian_title: str) -> Optional[str]:
    file_title = normalize_title_for_match(filename)
    en_title = normalize_title_for_match(english_title)
    it_title = normalize_title_for_match(italian_title)

    if not file_title:
        return None

    en_score = similarity(file_title, en_title) if en_title else 0.0
    it_score = similarity(file_title, it_title) if it_title else 0.0

    if en_title and en_title in file_title:
        en_score += 0.20
    if it_title and it_title in file_title:
        it_score += 0.20

    if it_score >= 0.78 and it_score > en_score + 0.08:
        return "Italian"
    if en_score >= 0.78 and en_score > it_score + 0.08:
        return "English"

    return None


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTS


def is_sub_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUB_EXTS


def is_info_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in INFO_EXTS


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} - Version {counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def unique_folder_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 2
    while True:
        candidate = path.parent / f"{path.name} - {counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def score_title_candidate(candidate: str) -> int:
    candidate_clean = clean_text(candidate)
    candidate_low = candidate_clean.lower()

    score = 0
    words = candidate_clean.split()
    score += min(len(words) * 10, 50)

    for word in ["quiet", "place", "posto", "tranquillo", "mile"]:
        if re.search(rf"\b{re.escape(word)}\b", candidate_low, re.IGNORECASE):
            score += 5

    if re.search(r"\b(by|from|upload|uploaded)\b$", candidate_low):
        score -= 20

    if re.search(r"\b(netflixxe|netflix|org|movie|hollywood)\b", candidate_low):
        score -= 15

    return score


def resolve_numbered_franchise_title(name: str) -> Optional[str]:
    cleaned = strip_junk(Path(name).stem)
    cleaned_low = cleaned.lower()

    for franchise, mapping in FRANCHISE_NUMBERED_ALIASES.items():
        m = re.match(rf"^{re.escape(franchise)}\s+(\d+)\b", cleaned_low, flags=re.IGNORECASE)
        if m:
            num = m.group(1)
            return mapping.get(num)

    return None


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

    if TMDB_API_KEY and deduped:
        title, year, found_tmdb_id, score = resolve_tmdb_match(deduped, fallback_year=local_year)
        if found_tmdb_id and title:
            resolved_title = title
            resolved_year = year or local_year
            tmdb_id = found_tmdb_id
            confidence = score
            localized_titles = get_tmdb_localized_titles(found_tmdb_id)

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


def build_folder_base_name(title: str, year: Optional[str], tmdb_id: Optional[int] = None) -> str:
    title = title_case_safely(clean_text(title))
    year_str = f" ({year})" if year else ""
    id_str = f" [tmdbid-{tmdb_id}]" if tmdb_id else ""
    return f"{title}{year_str}{id_str}"


def rename_item(old_path: Path, new_path: Path, apply_changes: bool) -> Path:
    if old_path.resolve() == new_path.resolve():
        return old_path

    if old_path.name == new_path.name and old_path.parent == new_path.parent:
        return old_path

    target = unique_path(new_path)
    print(f"  {old_path.name}  ->  {target.name}")
    if apply_changes:
        old_path.rename(target)
    return target


def infer_movie_name_and_year(folder: Path) -> Tuple[str, Optional[str], str, Optional[int], Optional[dict]]:
    years: List[str] = []
    english_candidates: List[Tuple[str, int]] = []
    italian_candidates: List[Tuple[str, int]] = []
    video_languages: List[str] = []

    for item in folder.rglob("*"):
        if not item.is_file():
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
        if not TMDB_API_KEY:
            print(f"  [TMDb] Skipped for '{best_title}' because TMDB_API_KEY is missing.")
        else:
            resolved_title, resolved_year, found_tmdb_id, confidence = resolve_tmdb_match(combined_candidates)

            if found_tmdb_id and resolved_year and confidence >= 0.70:
                print(f"  [TMDb] Matched '{best_title}' -> '{resolved_title}' ({resolved_year}) [score={confidence:.2f}]")
                best_title = resolved_title
                best_year = resolved_year
                tmdb_id = found_tmdb_id
                localized_titles = get_tmdb_localized_titles(found_tmdb_id)
            elif resolved_year:
                print(f"  [REVIEW] Weak TMDb match for '{best_title}' -> '{resolved_title}' ({resolved_year}) [score={confidence:.2f}]")
            else:
                print(f"  [TMDb] No confident year found for '{best_title}'")

    if not localized_titles and TMDB_API_KEY and best_title and best_year:
        resolved_title, resolved_year, found_tmdb_id, confidence = resolve_tmdb_match(combined_candidates, fallback_year=best_year)
        if found_tmdb_id and confidence >= 0.70:
            tmdb_id = found_tmdb_id
            localized_titles = get_tmdb_localized_titles(found_tmdb_id)

    return best_title, best_year, folder_language, tmdb_id, localized_titles


def process_movie_folder(folder: Path, apply_changes: bool = False) -> None:
    print(f"\n=== {folder}")

    title, year, folder_language, tmdb_id, localized_titles = infer_movie_name_and_year(folder)

    source_dir = folder
    subdirs = [p for p in folder.iterdir() if p.is_dir()]
    files_here = [p for p in folder.iterdir() if p.is_file()]
    if len(subdirs) == 1 and not files_here:
        source_dir = subdirs[0]
        print(f"  Using nested source folder: {source_dir.name}")

    all_items = list(source_dir.iterdir())

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

        rename_item(vf, source_dir / new_name, apply_changes)

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

        rename_item(sf, source_dir / new_name, apply_changes)

    for nf in sorted(info_files, key=lambda p: p.name.lower()):
        new_name = f"{file_base_name}{nf.suffix.lower()}"
        rename_item(nf, source_dir / new_name, apply_changes)

    final_folder_path = folder.parent / base_name_folder
    current_main_folder = folder

    if current_main_folder.name != base_name_folder:
        print(f"  Folder {current_main_folder.name}  ->  {base_name_folder}")
        if apply_changes:
            current_main_folder.rename(unique_folder_path(final_folder_path))
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

def split_multi_movie_folder(folder: Path, apply_changes: bool = False) -> bool:
    if not folder.exists() or not folder.is_dir():
        print(f"  [SKIP] Folder does not exist: {folder}")
        return False
    
    all_items = list(folder.iterdir())
    video_files = [p for p in all_items if is_video_file(p)]
    subdirs = [p for p in all_items if p.is_dir()]

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

            if apply_changes:
                target_folder.mkdir(exist_ok=True)
                src.rename(unique_path(target_file))

    if unresolved:
        review_folder = folder / "_Needs_Review"
        for info in unresolved:
            src = info["source"]
            print(f"  [REVIEW] {src.name}")
            if apply_changes:
                review_folder.mkdir(exist_ok=True)
                src.rename(unique_path(review_folder / src.name))

    return True

def is_season_folder_name(name: str) -> bool:
    return re.match(r"^season[\s._-]*\d+$", name.strip(), flags=re.IGNORECASE) is not None


def detect_show_root(folder: Path) -> bool:
    """
    A folder is considered a show root if it contains at least one season-like subfolder.
    Example:
      Assassination_Classroom/
        Season_1/
        Season_2/
    """
    if not folder.is_dir():
        return False

    for item in folder.iterdir():
        if item.is_dir() and is_season_folder_name(item.name):
            return True
    return False


def extract_season_number_from_folder(name: str) -> Optional[int]:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None

def extract_episode_number(filename: str) -> Optional[int]:
    """
    Tries multiple patterns:
      S01E01
      1x03
      S1 (1)
      S1 Ep (1)
      S2 Ep 14
      Episode 03
      E05
      (12)
    """
    stem = Path(filename).stem

    patterns = [
        r"\bS\d{1,2}E(\d{1,3})\b",
        r"\b\d{1,2}x(\d{1,3})\b",
        r"\bep(?:isode)?[\s._-]*\(?(\d{1,3})\)?\b",
        r"\be[\s._-]?(\d{1,3})\b",
        r"\(\s*(\d{1,3})\s*\)",
        r"\b(\d{1,3})\b$",
    ]

    for pat in patterns:
        m = re.search(pat, stem, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))

    return None

def extract_season_number_from_filename(filename: str) -> Optional[int]:
    """
    Detect season number from filenames like:
      S01E01
      1x03
    """
    stem = Path(filename).stem

    patterns = [
        r"\bS(\d{1,2})E\d{1,3}\b",
        r"\b(\d{1,2})x\d{1,3}\b",
    ]

    for pat in patterns:
        m = re.search(pat, stem, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))

    return None

def sanitize_series_title(title: str) -> str:
    """
    Clean a series name for folder/file use.
    """
    title = clean_text(title)
    title = re.sub(r"\bseason[\s._-]*\d+\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    return title_case_safely(title)


def infer_series_name_from_folder(folder: Path) -> str:
    """
    For a structure like:
      Assassination_Classroom/Season_1/...
    the series name should be 'Assassination Classroom'
    """
    return sanitize_series_title(folder.name)


def rename_show_episode_file(
    file_path: Path,
    series_title: str,
    season_num: int,
    episode_num: int,
    apply_changes: bool = False
) -> Path:
    new_name = f"{series_title} S{season_num:02d}E{episode_num:02d}{file_path.suffix.lower()}"
    return rename_item(file_path, file_path.parent / new_name, apply_changes)

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
        [p for p in show_root.iterdir() if p.is_dir() and is_season_folder_name(p.name)],
        key=lambda p: p.name.lower()
    )

    for season_dir in season_dirs[:2]:
        episode_files = sorted(
            [p for p in season_dir.iterdir() if is_video_file(p)],
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
        [p for p in show_root.iterdir() if is_video_file(p)],
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

    if TMDB_API_KEY:
        title, year, found_tmdb_id, confidence = resolve_tmdb_tv_match(deduped)
        if found_tmdb_id and title and confidence >= 0.60:
            print(f"  [TMDb TV] Matched '{local_guess}' -> '{title}' ({year}) [score={confidence:.2f}]")
            resolved_name = title
            resolved_year = year
            tmdb_id = found_tmdb_id
            localized_titles = get_tmdb_tv_localized_titles(found_tmdb_id)
        elif title:
            print(f"  [REVIEW] Weak TMDb TV match for '{local_guess}' -> '{title}' ({year}) [score={confidence:.2f}]")

    return resolved_name, resolved_year, tmdb_id, localized_titles

def process_show_folder(show_root: Path, apply_changes: bool = False) -> None:
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
        if apply_changes:
            target = unique_folder_path(show_root.parent / desired_root_name)
            show_root.rename(target)
            show_root = target

    season_dirs = sorted(
        [p for p in show_root.iterdir() if p.is_dir() and is_season_folder_name(p.name)],
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
            if apply_changes:
                target = unique_folder_path(season_dir.parent / normalized_season_name)
                season_dir.rename(target)
                season_dir = target

        episode_files = sorted(
            [p for p in season_dir.iterdir() if is_video_file(p)],
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

            new_name = f"{series_title}"
            if series_year:
                new_name += f" ({series_year})"
            new_name += f" S{season_num:02d}E{ep_num:02d}{ep_file.suffix.lower()}"

            rename_item(ep_file, ep_file.parent / new_name, apply_changes)

def process_flat_show_folder(show_root: Path, apply_changes: bool = False) -> None:
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
        if apply_changes:
            target = unique_folder_path(show_root.parent / desired_root_name)
            show_root.rename(target)
            show_root = target

    episode_files = sorted(
        [p for p in show_root.iterdir() if is_video_file(p)],
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
        new_name = f"{series_title}"
        if series_year:
            new_name += f" ({series_year})"
        new_name += f" S{season_num:02d}E{episode_num:02d}{ep_file.suffix.lower()}"

        print(f"  Episode folder -> {season_folder_name}")
        print(f"  {ep_file.name}  ->  {new_name}")

        if apply_changes:
            target_season_dir.mkdir(exist_ok=True)
            rename_item(ep_file, target_season_dir / new_name, apply_changes=True)

def is_reserved_library_folder(path: Path) -> bool:
    return path.name.lower() in {MOVIES_DIRNAME.lower(), SHOWS_DIRNAME.lower()}


def get_media_subfolders(root: Path) -> List[Path]:
    """
    Return top-level folders in the media root, excluding reserved library folders.
    """
    folders = []
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue
        if is_reserved_library_folder(item):
            continue
        folders.append(item)
    return folders


def ensure_library_dirs(root: Path, apply_changes: bool) -> tuple[Path, Path]:
    movies_dir = root / MOVIES_DIRNAME
    shows_dir = root / SHOWS_DIRNAME

    if apply_changes:
        movies_dir.mkdir(exist_ok=True)
        shows_dir.mkdir(exist_ok=True)

    return movies_dir, shows_dir

def move_folder_to_library(folder: Path, library_dir: Path, apply_changes: bool) -> Path:
    """
    Move a top-level folder into the target library directory.
    In dry run it only prints the move and returns the original path,
    because nothing has actually moved yet.
    In apply mode it returns the new real path.
    """
    target = library_dir / folder.name

    if folder.parent == library_dir:
        return folder

    final_target = unique_folder_path(target)

    print(f"  Library move {folder}  ->  {final_target}")

    if apply_changes:
        folder.rename(final_target)
        return final_target

    # In dry run, keep using the original folder path because it still exists
    return folder

def process_entry_with_library_routing(entry: Path, media_root: Path, apply_changes: bool) -> None:
    """
    Route a top-level media folder into 0_Movies or 0_Shows, then process it.
    """
    movies_dir, shows_dir = ensure_library_dirs(media_root, apply_changes=apply_changes)

    if detect_show_root(entry) or detect_flat_show_folder(entry):
        routed_entry = move_folder_to_library(entry, shows_dir, apply_changes=apply_changes)

        if detect_show_root(routed_entry):
            process_show_folder(routed_entry, apply_changes=apply_changes)
        else:
            process_flat_show_folder(routed_entry, apply_changes=apply_changes)
    else:
        routed_entry = move_folder_to_library(entry, movies_dir, apply_changes=apply_changes)

        handled = split_multi_movie_folder(routed_entry, apply_changes=apply_changes)
        if not handled:
            process_movie_folder(routed_entry, apply_changes=apply_changes)

def main():
    parser = argparse.ArgumentParser(
        description="Clean movie and show folders for Jellyfin with batch support."
    )
    parser.add_argument("root", help="Path to media root OR a single media folder")
    parser.add_argument("--apply", action="store_true", help="Actually rename/move files and folders")
    parser.add_argument("--batch-size", type=int, default=20, help="Number of top-level titles to process per batch")
    parser.add_argument("--batch-start", type=int, default=0, help="Zero-based start index of the batch")
    parser.add_argument("--single", action="store_true", help="Treat root as a single title folder instead of a library root")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Invalid folder: {root}")

    print(f"Scanning: {root}")
    print("Mode:", "APPLY" if args.apply else "DRY RUN")
    print("TMDb key loaded:", "YES" if TMDB_API_KEY else "NO")

    if args.single:
        if detect_show_root(root):
            process_show_folder(root, apply_changes=args.apply)
        elif detect_flat_show_folder(root):
            process_flat_show_folder(root, apply_changes=args.apply)
        else:
            handled = split_multi_movie_folder(root, apply_changes=args.apply)
            if not handled:
                process_movie_folder(root, apply_changes=args.apply)
        print("\nDone.")
        return

    # Library root mode
    entries = get_media_subfolders(root)
    total = len(entries)

    if total == 0:
        print("No media folders found.")
        print("\nDone.")
        return

    start = max(0, args.batch_start)
    end = min(start + max(1, args.batch_size), total)

    print(f"Batch: items {start} to {end - 1} of {total}")

    batch_entries = entries[start:end]

    for idx, entry in enumerate(batch_entries, start=start):
        print(f"\n##### [{idx}] {entry.name} #####")
        process_entry_with_library_routing(entry, media_root=root, apply_changes=args.apply)

    print("\nDone.")

if __name__ == "__main__":
    main()