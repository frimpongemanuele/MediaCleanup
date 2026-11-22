"""TMDb metadata lookup and match resolution."""

from __future__ import annotations

from typing import Optional, List, Tuple
import os
import requests
from .naming import (
    clean_text,
    similarity,
    title_case_safely,
)

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"

TMDB_DETAILS_URL = "https://api.themoviedb.org/3/movie/{movie_id}"

TMDB_TV_SEARCH_URL = "https://api.themoviedb.org/3/search/tv"

TMDB_TV_DETAILS_URL = "https://api.themoviedb.org/3/tv/{series_id}"


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
        print(f"  [TMDb] Search failed for '{title}': {type(e).__name__}")
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
        print(f"  [TMDb] Combined details failed for movie_id={movie_id}: {type(e).__name__}")
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
        print(f"  [TMDb TV] Search failed for '{title}': {type(e).__name__}")
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
        print(f"  [TMDb TV] Combined details failed for series_id={series_id}: {type(e).__name__}")
        return {}


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
