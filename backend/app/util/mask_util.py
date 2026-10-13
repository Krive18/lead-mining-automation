import re


PHONE_TOKEN_PATTERN = re.compile(
    r"(?<!\d)("
    r"1[3-9]\d{9}"
    r"|(?:0\d{2,3}[-\s]?)?\d{7,8}(?:[-\s]?\d{1,6})?"
    r"|400[-\s]?\d{3}[-\s]?\d{4}"
    r")(?!\d)"
)


def mask_phone(phone: str) -> str:
    if phone is None or phone == "":
        return ""

    def mask_single_phone(match: re.Match) -> str:
        raw_phone = match.group(1)
        digit_text = "".join(char for char in raw_phone if char.isdigit())
        if len(digit_text) < 7:
            return raw_phone
        return f"{digit_text[:3]}****{digit_text[-4:]}"

    masked_phone = PHONE_TOKEN_PATTERN.sub(mask_single_phone, phone)
    if masked_phone != phone:
        return masked_phone

    digit_list = [char for char in phone if char.isdigit()]
    if len(digit_list) < 7:
        return phone
    digit_text = "".join(digit_list)
    return f"{digit_text[:3]}****{digit_text[-4:]}"
