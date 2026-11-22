"""Pure filename parsing, normalization, and naming rules."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import re
from difflib import SequenceMatcher

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
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
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


def build_folder_base_name(title: str, year: Optional[str], tmdb_id: Optional[int] = None) -> str:
    title = title_case_safely(clean_text(title))
    year_str = f" ({year})" if year else ""
    id_str = f" [tmdbid-{tmdb_id}]" if tmdb_id else ""
    return f"{title}{year_str}{id_str}"


def is_season_folder_name(name: str) -> bool:
    return re.match(r"^season[\s._-]*\d+$", name.strip(), flags=re.IGNORECASE) is not None


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
