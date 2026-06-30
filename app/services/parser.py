import re

KEY_RE = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")

PHONE_RE = re.compile(
    r"(?:\+?7|8)[\s\-()]?\d{3}[\s\-()]?\d{3}[\s\-()]?\d{2}[\s\-()]?\d{2}"
)

APT_RE = re.compile(
    r"(?:кв(?:артира)?\.?|квартира)\s*[:№#-]?\s*(\d+)",
    re.I,
)

ADDRESS_RE = re.compile(
    r"((?:[А-Яа-яЁё\w.\-]+\s+){0,3}"
    r"(?:улица|ул\.?|проспект|пр\.?|пер\.?|переулок|шоссе|проезд)?\s*"
    r"[А-Яа-яЁё\w.\-]+\s*"
    r"(?:д\.?|дом)?\s*\d+[А-Яа-яA-Za-z/\-.]*"
    r"(?:\s*(?:к|корпус|литер)\.?\s*\d+)?"
    r"(?:\s*/\s*\d+)?)",
    re.I,
)


def normalize(value: str) -> str:
    value = (value or "").lower().replace("ё", "е")
    value = re.sub(r"\b(улица|ул\.|ул|дом|д\.)\b", "", value)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def parse_message(text: str) -> dict:
    clean_text = PHONE_RE.sub(" ", text or "")
    apartment_match = APT_RE.search(text or "")

    key_numbers = []

    for number in KEY_RE.findall(clean_text):
        if number not in key_numbers:
            key_numbers.append(number)

    address = ""

    lines = [
        line.strip(" ,.;")
        for line in (text or "").splitlines()
        if line.strip()
    ]

    for line in lines:
        has_address_words = re.search(
            r"(адрес|сочи|ул\.?|улица|шоссе|пер\.?|переулок|д\.?\s*\d|дом\s*\d)",
            line,
            re.I,
        )

        has_forbidden_words = re.search(
            r"(тел|ключ|фио|квартира|кв\.)",
            line,
            re.I,
        )

        if has_address_words and not has_forbidden_words:
            address = re.sub(
                r"^адрес\s*[:\-]?\s*",
                "",
                line,
                flags=re.I,
            ).strip()
            break

    if not address:
        match = ADDRESS_RE.search(text or "")
        address = match.group(1).strip(" ,.;") if match else ""

    phones = PHONE_RE.findall(text or "")

    return {
        "address": address,
        "apartment": apartment_match.group(1) if apartment_match else "",
        "key_numbers": key_numbers,
        "phones": phones,
    }