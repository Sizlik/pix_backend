def normalize_phone(phone: str) -> str:
    digits = "".join(character for character in phone if character.isdigit())
    if len(digits) == 10:
        return f"7{digits}"
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        return f"7{digits[1:]}"
    return digits


def phone_search_variants(phone: str) -> tuple[str, ...]:
    original = phone.strip()
    normalized = normalize_phone(original)
    if not original:
        return ()

    values = [original]
    if len(normalized) == 11 and normalized.startswith("7"):
        area = normalized[1:4]
        prefix = normalized[4:7]
        first_pair = normalized[7:9]
        second_pair = normalized[9:11]
        values.extend(
            [
                f"+7 ({area}) {prefix}-{first_pair}-{second_pair}",
                f"+7 {area} {prefix}-{first_pair}-{second_pair}",
                f"+7 {area} {prefix} {first_pair} {second_pair}",
                f"+7{normalized[1:]}",
                normalized,
                f"8 ({area}) {prefix}-{first_pair}-{second_pair}",
                f"8 {area} {prefix}-{first_pair}-{second_pair}",
                f"8{normalized[1:]}",
            ]
        )
    elif normalized:
        values.append(normalized)

    return tuple(dict.fromkeys(values))
