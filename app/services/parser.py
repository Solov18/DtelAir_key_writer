import re
import unicodedata
from difflib import SequenceMatcher

from app.db import db


PHONE_RE = re.compile(
    r"(?:\+?7|8)[\s-]*\(?\d{3}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
)

PRICE_RE = re.compile(
    r"\b\d+\s*(?:руб(?:\.|лей)?|р\.?|₽)\b",
    re.IGNORECASE,
)

APARTMENT_RE = re.compile(
    r"(?:кв(?:артира|[\s.-]*ра)?|ап(?:артамент(?:ы)?)?)"
    r"[\s.]*[:№#-]?\s*(\d+[а-яa-z]?(?:/\d+)?)",
    re.IGNORECASE,
)

ENTRANCE_RE = re.compile(
    r"(?:подъезд|под[\s.-]*езд|под\.?|п[\s.-]*д)"
    r"\s*[:№#-]?\s*(\d+)",
    re.IGNORECASE,
)

KEY_RE = re.compile(r"(?:№|#)?\s*(\d{4,7})(?!\d)")

HOUSE_MARKER_RE = re.compile(
    r"(?:\bдом\b|\bд\.?)\s*[:№#-]?\s*"
    r"(\d+[а-яa-z]?(?:\s*(?:корп(?:ус)?|к)\.?\s*\d+[а-яa-z]?)?)",
    re.IGNORECASE,
)

HOUSE_RE = re.compile(
    r"^\d+[а-яa-z]?(?:/(?:\d+[а-яa-z]?|стр\d+[а-яa-z]?|лит[а-яa-z])){0,2}$",
    re.IGNORECASE,
)

ADDRESS_TYPE_TOKENS = {
    "улица",
    "проспект",
    "переулок",
    "шоссе",
    "проезд",
    "бульвар",
    "набережная",
    "микрорайон",
    "площадь",
    "тупик",
    "тракт",
    "аллея",
    "квартал",
    "ст",
    "снт",
    "тсн",
    "днт",
    "жк",
}

CITY_AND_NOISE_TOKENS = {
    "город",
    "г",
    "сочи",
    "адлер",
    "адрес",
    "район",
    "рн",
    "россия",
}

OPERATION_NOISE_RE = re.compile(
    (
        r"\b("
        r"прошу|прописать|пропиши|записать|запиши|добавить|добавь|"
        r"нужно|надо|пожалуйста|ключ|ключа|ключи|ключей|"
        r"доп|бп|шт|штук|платно|бесплатно|стандарт|"
        r"телефон|тел|номер|заявка|заявке|жилец|жильцу"
        r")\b"
    ),
    re.IGNORECASE,
)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _replace_address_abbreviations(value: str) -> str:
    replacements = (
        (r"\bд(?=\d)", " "),
        (r"\bпр[\s.-]*т\b", " проспект "),
        (r"\bпросп\.?\b", " проспект "),
        (r"\bул\.?\b", " улица "),
        (r"\bпер\.?\b", " переулок "),
        (r"\bш\.?\b", " шоссе "),
        (r"\bбул\.?\b", " бульвар "),
        (r"\bнаб\.?\b", " набережная "),
        (r"\bмкр(?:н)?\.?\b", " микрорайон "),
        (r"\bпл\.?\b", " площадь "),
        (r"\bпр[\s.-]*д\b", " проезд "),
        (r"\bстр\.?\b", " строение "),
        (r"\bкорп\.?\b", " корпус "),
        (r"\bлит\.?\b", " литер "),
        (r"\bд\.?\b", " "),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.casefold().replace("ё", "е")
    value = _replace_address_abbreviations(value)

    # Дефисы и знаки препинания не должны влиять на совпадение улицы.
    value = re.sub(r"[_.,;:()\[\]{}№#'\"«»–—-]+", " ", value)
    value = re.sub(r"\\+", "/", value)
    value = re.sub(r"/\s+|\s+/", "/", value)
    return compact(value)


def normalize_house_variants(value: str) -> str:
    value = normalize(value)

    # Литеру дома часто отделяют пробелом: «Единство 1 А» и «Единство 1А»
    # должны обозначать один адрес. Склеиваем только число и одну букву,
    # непосредственно стоящую перед концом адреса или маркером корпуса.
    value = re.sub(
        r"\b(\d+)\s+([а-яa-z])(?=\s*(?:(?:корпус|корп|к)\s*\d+\b|$))",
        r"\1\2",
        value,
        flags=re.IGNORECASE,
    )

    # 65 корп. 1, 65к1 и 65/1 приводятся к одному виду.
    value = re.sub(
        r"\b(\d+[а-яa-z]?)\s*(?:корпус|корп|к)\s*(\d+[а-яa-z]?)\b",
        r"\1/\2",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(\d+[а-яa-z]?)\s*(?:строение|стр)\s*(\d+)\b",
        r"\1/стр\2",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(\d+)\s*(?:литер|лит)\s*([а-яa-z])\b",
        r"\1/лит\2",
        value,
        flags=re.IGNORECASE,
    )
    return compact(value)


def expand_tokens(tokens: list[str]) -> set[str]:
    result: set[str] = set()
    for token in tokens:
        result.add(token)
        if "/" not in token:
            continue
        parts = token.split("/")
        current = parts[0]
        result.add(current)
        for part in parts[1:]:
            current = f"{current}/{part}"
            result.add(current)
    return result


def remove_noise(text: str) -> str:
    value = text or ""
    value = PHONE_RE.sub(" ", value)
    value = PRICE_RE.sub(" ", value)
    value = APARTMENT_RE.sub(" ", value)
    value = ENTRANCE_RE.sub(" ", value)
    value = re.sub(r"(?:№|#)\s*\d{4,7}", " ", value)

    # Номер ключа нередко пишут без №. Длинные числа убираем из адресной
    # части, но сохраняем их, если перед числом явно написано «дом» или «д.».
    def strip_unmarked_key_number(match: re.Match) -> str:
        prefix = value[max(0, match.start() - 12):match.start()]
        if re.search(
            r"(?:\bдом\b|\bд\.?)\s*[:№#-]?\s*$",
            prefix,
            re.IGNORECASE,
        ):
            return match.group(0)
        return " "

    value = re.sub(r"(?<!\w)\d{4,7}(?!\w)", strip_unmarked_key_number, value)
    value = OPERATION_NOISE_RE.sub(" ", value)
    return normalize_house_variants(value)


def extract_phones(text: str) -> list[str]:
    result: list[str] = []
    for phone in PHONE_RE.findall(text or ""):
        clean_phone = compact(phone)
        if clean_phone and clean_phone not in result:
            result.append(clean_phone)
    return result


def extract_apartment(text: str) -> str:
    match = APARTMENT_RE.search(text or "")
    return match.group(1) if match else ""


def extract_entrance(text: str) -> str:
    match = ENTRANCE_RE.search(text or "")
    return match.group(1) if match else ""


def _house_number_parts(value: str) -> tuple[str, str]:
    normalized = normalize_house_variants(value)
    if not normalized:
        return "", ""
    token = normalized.split()[0]
    base, _, suffix = token.partition("/")
    return base, suffix


def extract_key_numbers(
    text: str,
    excluded_house_numbers: set[str] | None = None,
) -> list[str]:
    source = text or ""
    source = PHONE_RE.sub(" ", source)
    source = PRICE_RE.sub(" ", source)
    source = APARTMENT_RE.sub(" ", source)
    source = ENTRANCE_RE.sub(" ", source)
    source = HOUSE_MARKER_RE.sub(" ", source)

    excluded = {
        re.sub(r"\D", "", value or "")
        for value in (excluded_house_numbers or set())
        if re.sub(r"\D", "", value or "")
    }
    numbers: list[str] = []
    for number in KEY_RE.findall(source):
        if number in excluded:
            continue
        if number not in numbers:
            numbers.append(number)
    return numbers


def split_address_tokens(address: str) -> dict:
    tokens = normalize_house_variants(address).split()
    street_tokens: list[str] = []
    extra_tokens: list[str] = []
    house = ""

    for token in tokens:
        if token in CITY_AND_NOISE_TOKENS or token in ADDRESS_TYPE_TOKENS:
            continue
        if not house and HOUSE_RE.match(token):
            house = token
            continue
        if house:
            extra_tokens.append(token)
            continue
        if not token.isdigit():
            street_tokens.append(token)

    return {
        "street_tokens": street_tokens,
        "house": house,
        "extra_tokens": extra_tokens,
        "tokens": tokens,
    }


def get_panel_addresses() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                MIN(address) AS address,
                COUNT(*) AS panel_count,
                STRING_AGG(
                    DISTINCT entrance,
                    ',' ORDER BY entrance
                ) AS entrances
            FROM panels
            WHERE enabled = 1
              AND address IS NOT NULL
              AND TRIM(address) != ''
            GROUP BY SMART_NORM(address)
            ORDER BY SMART_NORM(MIN(address))
            """
        ).fetchall()

    result: list[dict] = []
    for row in rows:
        address = compact(row["address"])
        parsed = split_address_tokens(address)
        if not address or not parsed["street_tokens"] or not parsed["house"]:
            continue
        result.append(
            {
                "address": address,
                "panel_count": int(row["panel_count"] or 0),
                "entrances": row["entrances"] or "",
                **parsed,
            }
        )
    return result


def _token_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 4 and len(right) >= 4:
        if left.startswith(right) or right.startswith(left):
            return 0.93
    return SequenceMatcher(None, left, right).ratio()


def _street_similarity(message_tokens: set[str], street_tokens: list[str]) -> float:
    searchable = {
        token
        for token in message_tokens
        if token not in ADDRESS_TYPE_TOKENS
        and token not in CITY_AND_NOISE_TOKENS
        and not HOUSE_RE.match(token)
        and len(token) > 1
    }
    if not searchable or not street_tokens:
        return 0.0

    scores = [
        max((_token_similarity(token, candidate) for candidate in searchable), default=0.0)
        for token in street_tokens
    ]
    if min(scores, default=0.0) < 0.58:
        return 0.0
    return sum(scores) / len(scores)


def _house_similarity(message_tokens: set[str], candidate_house: str) -> tuple[float, str]:
    house_tokens = [token for token in message_tokens if HOUSE_RE.match(token)]
    if not house_tokens:
        return 0.18, "house_missing"

    # Полное совпадение допустимо только по исходному нормализованному номеру
    # дома. expand_tokens("21а/1") также содержит "21а", из-за чего адрес без
    # корпуса ошибочно считался точным при запросе "21А К1".
    if candidate_house in house_tokens:
        return 1.0, "house_exact"

    candidate_base, candidate_suffix = _house_number_parts(candidate_house)
    for message_house in house_tokens:
        message_base, message_suffix = _house_number_parts(message_house)
        if candidate_base == message_base:
            if candidate_suffix == message_suffix:
                return 1.0, "house_exact"
            return 0.76, "house_base"

    numeric_base = re.match(r"\d+", candidate_base)
    if numeric_base:
        candidate_number = int(numeric_base.group())
        for message_house in house_tokens:
            message_match = re.match(r"\d+", message_house)
            if message_match and abs(candidate_number - int(message_match.group())) <= 2:
                return 0.28, "house_near"
    return 0.0, "house_other"


def score_address(message_tokens: set[str], item: dict) -> int:
    """Compatibility score used by older callers: 0..1000."""
    street_score = _street_similarity(message_tokens, item["street_tokens"])
    if not street_score:
        return 0
    house_score, _ = _house_similarity(message_tokens, item["house"])
    return round((street_score * 0.42 + house_score * 0.58) * 1000)


def find_address_candidates(
    text: str,
    limit: int = 6,
    *,
    address_catalog: list[dict] | None = None,
) -> list[dict]:
    message = remove_noise(text)
    message_tokens = set(message.split())
    ranked: list[dict] = []

    for item in address_catalog if address_catalog is not None else get_panel_addresses():
        street_score = _street_similarity(message_tokens, item["street_tokens"])
        if street_score < 0.58:
            continue

        house_score, house_kind = _house_similarity(message_tokens, item["house"])
        score = (street_score * 0.42) + (house_score * 0.58)

        # Без совпадения дома адрес остаётся только подсказкой.
        if house_kind == "house_other":
            score *= 0.72

        if score < 0.48:
            continue

        if house_kind == "house_exact" and street_score >= 0.98:
            label = "Точное совпадение"
        elif house_kind == "house_exact":
            label = "Похожее написание"
        elif house_kind == "house_base":
            label = "Уточните корпус или строение"
        elif house_kind == "house_missing":
            label = "Совпала улица — уточните дом"
        else:
            label = "Похожий адрес"

        ranked.append(
            {
                "address": item["address"],
                "confidence": round(score, 3),
                "match_label": label,
                "panel_count": item["panel_count"],
                "entrances": item["entrances"],
                "house": item["house"],
                "house_match": house_kind,
                "street_confidence": round(street_score, 3),
            }
        )

    ranked.sort(
        key=lambda item: (
            -item["confidence"],
            item["address"].casefold(),
        )
    )
    return ranked[: max(1, min(int(limit), 12))]


def _select_detected_address(candidates: list[dict]) -> tuple[str, str]:
    if not candidates:
        return "", "not_found"

    best = candidates[0]
    second_score = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
    clear_lead = best["confidence"] - second_score >= 0.045

    if (
        best["house_match"] == "house_exact"
        and best["confidence"] >= 0.78
        and (clear_lead or best["confidence"] >= 0.985)
    ):
        return best["address"], (
            "exact" if best["confidence"] >= 0.985 else "similar"
        )

    if (
        best["house_match"] == "house_base"
        and best["confidence"] >= 0.78
        and clear_lead
    ):
        return best["address"], "similar"

    return "", "needs_confirmation"


def extract_address_from_db(text: str) -> str:
    address, _ = _select_detected_address(find_address_candidates(text))
    return address


def extract_key_type(text: str) -> str:
    source = normalize(text)
    match = re.search(
        r"ключ(?:а|ей|и)?\s+"
        r"([а-яa-z][а-яa-z0-9\s-]{0,30}?)"
        r"\s+(?:№|#)?\d{4,7}\b",
        source,
        re.IGNORECASE,
    )
    if not match:
        return ""

    value = re.sub(
        r"\b(бп|доп|платно|бесплатно|ключ|ключа|ключи|ключей)\b",
        " ",
        match.group(1),
        flags=re.IGNORECASE,
    )
    return compact(value)


_KEY_TYPE_ALIASES = {
    "оранж": ("оранжев",),
    "оранжевый": ("оранжев",),
    "уник": ("уникальн",),
    "уникальный": ("уникальн",),
    "стикер": ("стикер",),
    "sticker": ("стикер",),
    "розовый": ("розов",),
    "бесплатный розовый": ("бесплат", "розов"),
    "прост": ("прост",),
    "простой": ("прост",),
    "премиум": ("преми",),
    "премиальный": ("преми",),
}

_KEY_GROUP_MARKERS = {
    "оранжевые": ("оранжев",),
    "оранжевый": ("оранжев",),
    "стикеры": ("стикер",),
    "стикер": ("стикер",),
    "уникальные": ("уникальн",),
    "уникальный": ("уникальн",),
    "простые": ("прост",),
    "простой": ("прост",),
    "премиальные": ("преми",),
    "премиальный": ("преми",),
}


def _normalized_key_type(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return compact(re.sub(r"[^0-9a-zа-я]+", " ", value))


def _key_type_catalog() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM key_types WHERE enabled = 1 ORDER BY LENGTH(name) DESC, LOWER(name)"
        ).fetchall()
    return [dict(row) for row in rows]


def _type_aliases(type_name: str) -> set[str]:
    normalized = _normalized_key_type(type_name)
    aliases = {normalized}
    for alias, markers in _KEY_TYPE_ALIASES.items():
        if all(marker in normalized for marker in markers):
            aliases.add(alias)
    return {alias for alias in aliases if alias}


def _catalog_type_by_markers(catalog: list[dict], markers: tuple[str, ...]) -> dict | None:
    matches = [
        item for item in catalog
        if all(marker in _normalized_key_type(item["name"]) for marker in markers)
    ]
    return matches[0] if len(matches) == 1 else None


def _extract_grouped_key_requests(source: str, catalog: list[dict]) -> list[dict]:
    """Parse one-line key groups while preserving printed numbers and their types."""
    grouped: list[dict] = []
    line_pattern = re.compile(
        r"(?im)^\s*(ключи|оранжевые?|стикеры?|уникальные?|простые|простой|"
        r"премиальные|премиальный)\s*[:\-—–]\s*([^\r\n]*)"
    )
    suffix_markers = {
        "ор": ("оранжев",), "оранж": ("оранжев",), "оранжевый": ("оранжев",),
        "ст": ("стикер",), "стикер": ("стикер",),
        "уник": ("уникальн",), "уникальный": ("уникальн",),
        "прост": ("прост",), "простой": ("прост",),
        "прем": ("преми",), "премиальный": ("преми",),
    }

    for match in line_pattern.finditer(source):
        label = _normalized_key_type(match.group(1))
        value = match.group(2).strip()
        if not value or re.fullmatch(r"[-—–\s]*", value):
            continue
        markers = _KEY_GROUP_MARKERS.get(label)
        if markers:
            key_type = _catalog_type_by_markers(catalog, markers)
            if not key_type:
                continue
            for number_match in re.finditer(r"(?<!\d)(\d{1,7})(?!\d)", value):
                grouped.append({
                    "number": number_match.group(1), "type_id": int(key_type["id"]),
                    "type_name": key_type["name"], "type_text": match.group(1),
                    "hex_value": "", "position": match.start(2) + number_match.start(),
                })
            continue

        for number_match in re.finditer(r"(?<!\d)(\d{1,7})(?!\d)\s*([a-zа-я]+)?", value, re.IGNORECASE):
            suffix = _normalized_key_type(number_match.group(2) or "")
            key_type = _catalog_type_by_markers(catalog, suffix_markers[suffix]) if suffix in suffix_markers else None
            if key_type:
                grouped.append({
                    "number": number_match.group(1), "type_id": int(key_type["id"]),
                    "type_name": key_type["name"], "type_text": number_match.group(2) or "",
                    "hex_value": "", "position": match.start(2) + number_match.start(),
                })
    return grouped


def extract_key_requests(
    text: str,
    excluded_house_numbers: set[str] | None = None,
) -> list[dict]:
    """Return typed key references without converting printed numbers to integers."""
    source = unicodedata.normalize("NFKC", str(text or ""))
    occupied: list[tuple[int, int]] = []
    requests: list[dict] = []

    catalog = _key_type_catalog()
    requests.extend(_extract_grouped_key_requests(source, catalog))
    alias_candidates: dict[str, list[dict]] = {}
    for key_type in catalog:
        for alias in _type_aliases(key_type["name"]):
            alias_candidates.setdefault(alias, []).append(key_type)

    alias_rows: list[tuple[str, dict]] = []
    for alias, candidates in alias_candidates.items():
        exact = [item for item in candidates if _normalized_key_type(item["name"]) == alias]
        if len(exact) == 1:
            alias_rows.append((alias, exact[0]))
        elif len(candidates) == 1:
            alias_rows.append((alias, candidates[0]))
        # An alias shared by several catalog types is intentionally ignored:
        # the operator must name the type more precisely.
    alias_rows.sort(key=lambda item: len(item[0]), reverse=True)

    for alias, key_type in alias_rows:
        alias_pattern = r"\s+".join(re.escape(part) for part in alias.split())
        pattern = re.compile(
            rf"(?<![\w])({alias_pattern})(?![\w])\s*(?:[-—–:]\s*)?(?:№|#)?\s*(\d{{1,7}})(?!\d)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(source):
            if any(start < match.end() and match.start() < end for start, end in occupied):
                continue
            number = match.group(2)
            requests.append(
                {
                    "number": number,
                    "type_id": int(key_type["id"]),
                    "type_name": key_type["name"],
                    "type_text": match.group(1),
                    "hex_value": (
                        re.search(
                            r"(?:hex|uid|код)\s*[:№#-]?\s*([0-9a-f]{6,16})",
                            source[match.end():match.end() + 48],
                            re.IGNORECASE,
                        ).group(1).upper()
                        if re.search(
                            r"(?:hex|uid|код)\s*[:№#-]?\s*([0-9a-f]{6,16})",
                            source[match.end():match.end() + 48],
                            re.IGNORECASE,
                        )
                        else ""
                    ),
                    "position": match.start(),
                }
            )
            occupied.append((match.start(), match.end()))

    typed_numbers = {item["number"] for item in requests}
    for number in extract_key_numbers(source, excluded_house_numbers):
        if number in typed_numbers:
            continue
        match = re.search(rf"(?<!\d){re.escape(number)}(?!\d)", source)
        requests.append(
            {
                "number": number,
                "type_id": None,
                "type_name": "",
                "type_text": "",
                "hex_value": "",
                "position": match.start() if match else len(source),
            }
        )

    if not requests:
        hex_match = re.search(
            r"(?:hex|uid|код)\s*[:№#-]?\s*([0-9a-f]{6,16})",
            source,
            re.IGNORECASE,
        )
        if hex_match:
            value = hex_match.group(1).upper()
            requests.append(
                {
                    "number": value,
                    "type_id": None,
                    "type_name": "",
                    "type_text": "",
                    "hex_value": value,
                    "position": hex_match.start(),
                }
            )

    requests.sort(key=lambda item: item.pop("position"))
    unique: list[dict] = []
    fingerprints: set[tuple[int | None, str]] = set()
    for request in requests:
        fingerprint = (request["type_id"], request["number"])
        if fingerprint not in fingerprints:
            fingerprints.add(fingerprint)
            unique.append(request)
    return unique


def parse_message(text: str) -> dict:
    address_candidates = find_address_candidates(text)
    address, address_status = _select_detected_address(address_candidates)
    excluded_houses = {
        candidate["house"]
        for candidate in address_candidates[:3]
        if candidate["confidence"] >= 0.7
    }

    key_requests = extract_key_requests(text, excluded_houses)
    return {
        "address": address,
        "address_status": address_status,
        "address_candidates": address_candidates,
        "address_hint": remove_noise(text),
        "apartment": extract_apartment(text),
        "entrance": extract_entrance(text),
        "key_numbers": [item["number"] for item in key_requests],
        "key_requests": key_requests,
        "key_type": ", ".join(dict.fromkeys(
            item["type_name"] for item in key_requests if item["type_name"]
        )) or extract_key_type(text),
        "phones": extract_phones(text),
    }
