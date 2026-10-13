import re


UNIFIED_SOCIAL_CREDIT_CODE_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
UNIFIED_SOCIAL_CREDIT_CODE_LABEL_PATTERN_LIST = [
    re.compile(
        r"(?:统一社会信用代码|社会信用代码|信用代码)\s*[:：]?\s*"
        r"([0-9A-HJ-NPQRTUWXY]{18})(?![0-9A-Z])",
        re.IGNORECASE,
    ),
    re.compile(
        r"[\"']?(?:unifiedSocialCreditCode|socialCreditCode|creditCode|credit_code)[\"']?"
        r"\s*[:=]\s*[\"']?([0-9A-HJ-NPQRTUWXY]{18})(?![0-9A-Z])",
        re.IGNORECASE,
    ),
]


def clean_unified_social_credit_code(value: str) -> str:
    clean_value = re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()
    if not UNIFIED_SOCIAL_CREDIT_CODE_PATTERN.fullmatch(clean_value):
        return ""
    return clean_value


def extract_unified_social_credit_code(text: str) -> str:
    raw_text = str(text or "")
    for pattern in UNIFIED_SOCIAL_CREDIT_CODE_LABEL_PATTERN_LIST:
        match = pattern.search(raw_text)
        if not match:
            continue
        credit_code = clean_unified_social_credit_code(match.group(1))
        if credit_code:
            return credit_code
    return ""
