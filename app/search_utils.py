import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable


_APARTMENT_QUERY_RE = re.compile(
    r"(?<![\w])кв(?:артира)?\.?\s*(?:№|#|no\.?)?\s*"
    r"(?P<apartment>\d+[а-яa-z]?(?:/\d+)?)\b",
    re.IGNORECASE,
)
_ADDRESS_NOISE_RE = re.compile(
    r"\b(?:улица|ул|дом|д|город|г|адрес|россия|сочи|адлер)\b\.?",
    re.IGNORECASE,
)
_HOUSE_PART_RE = re.compile(
    r"(?P<main>\d+[а-яa-z]?)\s*"
    r"(?:/|корп(?:ус)?\.?|к\.?|лит(?:ер)?\.?)\s*"
    r"(?P<part>\d+[а-яa-z]?|[а-яa-z])\b",
    re.IGNORECASE,
)
_HOUSE_RE = re.compile(r"(?<![\w])(?P<house>\d+[а-яa-z]?)(?![\w/])", re.IGNORECASE)
_SEPARATED_TECHNICAL_RE = re.compile(
    r"^(?:[0-9a-f]{2}[:-]){3,7}[0-9a-f]{2}$",
    re.IGNORECASE,
)


def normalize_search_text(value) -> str:
    """Normalize text for case- and punctuation-insensitive search."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("ё", "е")
    normalized = "".join(character for character in text if character.isalnum())
    if len(normalized) == 11 and normalized.isdigit() and normalized.startswith("8"):
        normalized = f"7{normalized[1:]}"
    return normalized


def normalize_apartment(value) -> str:
    """Return a stable value for exact apartment comparisons."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = normalized.replace("ё", "е")
    normalized = re.sub(r"[\s._-]+", "", normalized)
    match = re.fullmatch(r"0*(\d+)([а-яa-z]?)(?:/0*(\d+))?", normalized)
    if not match:
        return normalized
    main = str(int(match.group(1) or "0"))
    suffix = match.group(2) or ""
    fraction = match.group(3)
    return f"{main}{suffix}{f'/{int(fraction)}' if fraction else ''}"


def parse_assignment_search_query(value: str) -> dict:
    """Split a key-register query into address and apartment constraints.

    Apartment markers are removed before the address is parsed. This prevents
    an apartment number from ever being compared with a key number, HEX or a
    technical panel identifier.
    """
    raw_source = str(value or "").strip()
    compact_source = re.sub(r"\s+", "", raw_source)
    if _SEPARATED_TECHNICAL_RE.fullmatch(compact_source):
        return {
            "source": raw_source,
            "apartment": "",
            "has_apartment": False,
            "address_source": raw_source,
            "street_tokens": [],
            "house": "",
            "looks_like_address": False,
        }

    source = unicodedata.normalize("NFKC", raw_source).casefold()
    source = source.replace("ё", "е")
    apartment_match = _APARTMENT_QUERY_RE.search(source)
    apartment = (
        normalize_apartment(apartment_match.group("apartment"))
        if apartment_match
        else ""
    )
    address_source = source
    if apartment_match:
        address_source = (
            address_source[: apartment_match.start()]
            + " "
            + address_source[apartment_match.end() :]
        )

    address_source = re.sub(r"\s+", " ", address_source).strip(" ,.;")
    address = _ADDRESS_NOISE_RE.sub(" ", address_source)
    address = re.sub(r"[_.,;:()\[\]{}№#'\"«»–—-]+", " ", address)
    address = re.sub(r"\s+", " ", address).strip()

    house_match = _HOUSE_PART_RE.search(address) or _HOUSE_RE.search(address)
    house = ""
    if house_match:
        if house_match.groupdict().get("part"):
            house = f"{house_match.group('main')}/{house_match.group('part')}"
        else:
            house = house_match.group("house")
        street_source = address[: house_match.start()]
    else:
        street_source = address

    street_tokens = [
        token
        for token in re.findall(r"[а-яa-z]+", street_source, re.IGNORECASE)
        if token not in {"кв", "квартира"}
    ]
    looks_like_address = bool(street_tokens and house)
    return {
        "source": raw_source,
        "apartment": apartment,
        "has_apartment": bool(apartment_match),
        "address_source": address_source,
        "street_tokens": street_tokens,
        "house": house,
        "looks_like_address": looks_like_address,
    }


def assignment_address_sql(parsed: dict, column: str = "ka.address") -> tuple[str, list]:
    """Build PostgreSQL constraints for one exact house without an N+1 query."""
    conditions: list[str] = []
    params: list[str] = []
    for token in parsed.get("street_tokens") or []:
        conditions.append(f"SMART_NORM({column}) LIKE ?")
        params.append(f"%{normalize_search_text(token)}%")

    house = str(parsed.get("house") or "")
    if house:
        if "/" in house:
            main, part = house.split("/", 1)
            separator = r"(?:\s*/\s*|\s*(?:корп(?:ус)?\.?|к\.?|лит(?:ер)?\.?)\s*)"
            pattern = (
                rf"(^|[^0-9а-яa-z]){re.escape(main)}{separator}"
                rf"{re.escape(part)}($|[^0-9а-яa-z])"
            )
        else:
            pattern = (
                rf"(^|[^0-9а-яa-z]){re.escape(house)}"
                rf"($|[^0-9а-яa-z/])"
            )
        conditions.append(f"LOWER(REPLACE(COALESCE({column}, ''), 'ё', 'е')) ~ ?")
        params.append(pattern)

    return " AND ".join(conditions), params


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
