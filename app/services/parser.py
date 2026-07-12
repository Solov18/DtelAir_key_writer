import re

from app.db import db


PHONE_RE = re.compile(
    r"(?:\+?7|8)[\s\-()]?\d{3}[\s\-()]?\d{3}[\s\-()]?\d{2}[\s\-()]?\d{2}"
)

PRICE_RE = re.compile(
    r"\b\d+\s*(?:руб(?:\.|лей)?|р\.?|₽)\b",
    re.IGNORECASE,
)

APARTMENT_RE = re.compile(
    r"(?:кв(?:артира)?\.?|квартира)\s*[:№#-]?\s*(\d+)",
    re.IGNORECASE,
)

ENTRANCE_RE = re.compile(
    r"(?:подъезд|под\.?|п\.?)\s*[:№#-]?\s*(\d+)",
    re.IGNORECASE,
)

KEY_RE = re.compile(
    r"(?:№|#)?\s*(\d{4,6})(?!\d)"
)

HOUSE_RE = re.compile(
    r"^\d+[а-яa-z]?(?:/\d+[а-яa-z]?){0,2}$",
    re.IGNORECASE,
)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize(value: str) -> str:
    value = (value or "").lower().replace("ё", "е")

    value = re.sub(
        r"[.,;:()\[\]№#]+",
        " ",
        value,
    )

    replacements = {
        r"\bул\b": "улица",
        r"\bд\b": "",
        r"\bдом\b": "",
        r"\bпр\b": "проспект",
        r"\bпер\b": "переулок",
        r"\bбул\b": "бульвар",
        r"\bнаб\b": "набережная",
        r"\bкорп\b": "корпус",
        r"\bк\b": "корпус",
        r"\bлит\b": "литер",
        r"\bл\b": "литер",
    }

    for pattern, replacement in replacements.items():
        value = re.sub(
            pattern,
            replacement,
            value,
        )

    return compact(value)


def normalize_house_variants(value: str) -> str:
    value = normalize(value)

    # Приводим варианты:
    # "12 корпус 1"
    # "12 корп 1"
    # "12 к 1"
    # к единому виду "12/1"
    value = re.sub(
        r"\b(\d+[а-яa-z]?)\s+(?:корпус|корп|к)\s+(\d+)\b",
        r"\1/\2",
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
    value = normalize(text)

    value = PHONE_RE.sub(" ", value)
    value = PRICE_RE.sub(" ", value)
    value = APARTMENT_RE.sub(" ", value)
    value = ENTRANCE_RE.sub(" ", value)

    value = re.sub(
        r"№\s*\d{4,6}",
        " ",
        value,
    )

    value = re.sub(
        r"#\s*\d{4,6}",
        " ",
        value,
    )

    value = re.sub(
        r"\b\d{4,6}\b",
        " ",
        value,
    )

    value = re.sub(
        (
            r"\b("
            r"прошу|"
            r"прописать|"
            r"пропиши|"
            r"записать|"
            r"запиши|"
            r"добавить|"
            r"добавь|"
            r"нужно|"
            r"надо|"
            r"пожалуйста|"
            r"ключ|"
            r"ключа|"
            r"ключи|"
            r"ключей|"
            r"доп|"
            r"бп|"
            r"шт|"
            r"штук|"
            r"платно|"
            r"бесплатно|"
            r"стандарт"
            r")\b"
        ),
        " ",
        value,
        flags=re.IGNORECASE,
    )

    return compact(value)


def extract_phones(text: str) -> list[str]:
    return PHONE_RE.findall(text or "")


def extract_apartment(text: str) -> str:
    match = APARTMENT_RE.search(text or "")

    if not match:
        return ""

    return match.group(1)


def extract_entrance(text: str) -> str:
    match = ENTRANCE_RE.search(text or "")

    if not match:
        return ""

    return match.group(1)


def extract_key_numbers(text: str) -> list[str]:
    source = text or ""

    source = PHONE_RE.sub(" ", source)
    source = PRICE_RE.sub(" ", source)
    source = APARTMENT_RE.sub(" ", source)
    source = ENTRANCE_RE.sub(" ", source)

    numbers: list[str] = []

    for number in KEY_RE.findall(source):
        if number not in numbers:
            numbers.append(number)

    return numbers


def split_address_tokens(address: str) -> dict:
    tokens = normalize_house_variants(address).split()

    street_tokens: list[str] = []
    extra_tokens: list[str] = []
    house = ""

    address_type_tokens = {
        "улица",
        "проспект",
        "переулок",
        "шоссе",
        "проезд",
        "бульвар",
        "набережная",
        "дом",
    }

    for token in tokens:
        if not house and HOUSE_RE.match(token):
            house = token
            continue

        if house:
            extra_tokens.append(token)
            continue

        if token not in address_type_tokens:
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
            SELECT DISTINCT
                address,
                name,
                entrance
            FROM panels
            WHERE enabled = 1
              AND address IS NOT NULL
              AND TRIM(address) != ''
            ORDER BY address
            """
        ).fetchall()

    result: list[dict] = []

    for row in rows:
        address = compact(row["address"])

        if not address:
            continue

        parsed = split_address_tokens(address)

        if not parsed["street_tokens"]:
            continue

        if not parsed["house"]:
            continue

        result.append(
            {
                "address": address,
                "name": row["name"] or "",
                "entrance": row["entrance"] or "",
                "street_tokens": parsed["street_tokens"],
                "house": parsed["house"],
                "extra_tokens": parsed["extra_tokens"],
                "tokens": parsed["tokens"],
            }
        )

    return result


def score_address(
    message_tokens: set[str],
    item: dict,
) -> int:
    score = 0

    # Все слова названия улицы должны присутствовать в сообщении.
    for street_token in item["street_tokens"]:
        if street_token not in message_tokens:
            return 0

    score += len(item["street_tokens"]) * 200

    # Номер дома должен совпасть обязательно.
    if item["house"] not in message_tokens:
        return 0

    score += 1000

    # Корпус, литера и другие дополнительные части адреса.
    for token in item["extra_tokens"]:
        if token in message_tokens:
            score += 150

    # Более полный адрес получает небольшой дополнительный вес.
    score += len(item["tokens"])

    return score


def extract_address_from_db(text: str) -> str:
    message = normalize_house_variants(
        remove_noise(text)
    )

    message_tokens = expand_tokens(
        message.split()
    )

    best_address = ""
    best_score = 0

    for item in get_panel_addresses():
        score = score_address(
            message_tokens,
            item,
        )

        if score > best_score:
            best_score = score
            best_address = item["address"]

    return best_address


def extract_key_type(text: str) -> str:
    source = normalize(text)

    match = re.search(
        r"ключ(?:а|ей|и)?\s+([а-яa-z0-9\s]+?)\s*\d{4,6}",
        source,
        re.IGNORECASE,
    )

    if not match:
        return ""

    value = match.group(1)

    value = re.sub(
        r"\b(бп|доп|платно|бесплатно|ключ|ключа|ключи|ключей)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )

    return compact(value)


def parse_message(text: str) -> dict:
    return {
        "address": extract_address_from_db(text),
        "apartment": extract_apartment(text),
        "entrance": extract_entrance(text),
        "key_numbers": extract_key_numbers(text),
        "key_type": extract_key_type(text),
        "phones": extract_phones(text),
    }