import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable


def normalize_search_text(value) -> str:
    """Normalize text for case- and punctuation-insensitive search."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("ё", "е")
    normalized = "".join(character for character in text if character.isalnum())
    if len(normalized) == 11 and normalized.isdigit() and normalized.startswith("8"):
        normalized = f"7{normalized[1:]}"
    return normalized


def search_score(query: str, candidate: str) -> float:
    normalized_query = normalize_search_text(query)
    normalized_candidate = normalize_search_text(candidate)

    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0
    if normalized_candidate.startswith(normalized_query):
        return 0.96
    if normalized_query in normalized_candidate:
        coverage = len(normalized_query) / max(1, len(normalized_candidate))
        return 0.82 + min(0.12, coverage * 0.12)

    query_tokens = [
        normalize_search_text(token)
        for token in re.split(r"[\s,.;:/\\|_+\-–—()\[\]{}]+", str(query or ""))
        if normalize_search_text(token)
    ]
    candidate_tokens = [
        normalize_search_text(token)
        for token in re.split(r"[\s,.;:/\\|_+\-–—()\[\]{}]+", str(candidate or ""))
        if normalize_search_text(token)
    ]
    if query_tokens and all(
        any(
            candidate_token.startswith(query_token)
            or query_token in candidate_token
            for candidate_token in candidate_tokens
        )
        for query_token in query_tokens
    ):
        return 0.8

    return SequenceMatcher(
        None,
        normalized_query,
        normalized_candidate,
    ).ratio()


def matches_search(query: str, *values, threshold: float = 0.62) -> bool:
    if not normalize_search_text(query):
        return True
    return max(
        (search_score(query, value) for value in values),
        default=0.0,
    ) >= threshold


def rank_search_candidates(
    query: str,
    candidates: Iterable[dict],
    *,
    limit: int = 8,
) -> list[dict]:
    ranked: list[tuple[float, dict]] = []
    seen: set[str] = set()

    for item in candidates:
        value = str(item.get("value") or item.get("label") or "").strip()
        label = str(item.get("label") or value).strip()
        normalized_value = normalize_search_text(value)
        if not normalized_value or normalized_value in seen:
            continue

        score = max(
            search_score(query, value),
            search_score(query, label),
            search_score(query, item.get("search_text", "")),
        )
        if score < 0.5:
            continue

        seen.add(normalized_value)
        ranked.append(
            (
                score,
                {
                    "value": value,
                    "label": label,
                    "meta": str(item.get("meta") or "").strip(),
                },
            )
        )

    ranked.sort(
        key=lambda pair: (
            -pair[0],
            normalize_search_text(pair[1]["label"]),
        )
    )
    return [item for _, item in ranked[: max(1, min(int(limit), 12))]]
