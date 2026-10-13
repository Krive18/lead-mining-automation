import os
import re
from typing import Iterable, List


MOBILE_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
LANDLINE_PHONE_PATTERN = re.compile(r"(?<!\d)(0\d{2,3}[-\s]?\d{7,8})(?!\d)")
SERVICE_PHONE_PATTERN = re.compile(r"(?<!\d)((?:400|800)[-\s]?\d{3}[-\s]?\d{4})(?!\d)")

DISQUALIFIED_PHONE_SET = {"13800138000", "13800000000"}
PLATFORM_SERVICE_PHONE_SET = {"4006080000"}
DEFAULT_PRIVATE_PHONE_SET = {"13421110610"}


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


COLLECT_LANDLINE_PHONE = parse_bool(os.getenv("COLLECTOR_COLLECT_LANDLINE_PHONE"), False)


def compact_phone_text(phone: str) -> str:
    return re.sub(r"\D+", "", str(phone or ""))


def parse_phone_set(value: str) -> set:
    phone_set = set()
    for raw_phone in re.split(r"[,\s;；，、|]+", value or ""):
        compact_phone = compact_phone_text(raw_phone)
        if len(compact_phone) >= 7:
            phone_set.add(compact_phone)
    return phone_set


BLOCKED_PHONE_SET = (
    DISQUALIFIED_PHONE_SET
    | PLATFORM_SERVICE_PHONE_SET
    | DEFAULT_PRIVATE_PHONE_SET
    | parse_phone_set(os.getenv("COLLECTOR_BLOCKED_PHONE_LIST", ""))
)


def is_blocked_phone(phone: str) -> bool:
    compact_phone = compact_phone_text(phone)
    return bool(compact_phone and compact_phone in BLOCKED_PHONE_SET)


def is_landline_phone(phone: str) -> bool:
    return bool(LANDLINE_PHONE_PATTERN.fullmatch(str(phone or "").strip()))


def dedupe_public_phone_list(phone_list: Iterable[str], include_landline: bool = None) -> List[str]:
    if include_landline is None:
        include_landline = COLLECT_LANDLINE_PHONE
    result_list = []
    seen_compact_set = set()
    for phone in phone_list:
        clean_phone = re.sub(r"\s+", "", str(phone or "")).strip()
        compact_phone = compact_phone_text(clean_phone)
        if not compact_phone or compact_phone in seen_compact_set or compact_phone in BLOCKED_PHONE_SET:
            continue
        if not include_landline and is_landline_phone(clean_phone):
            continue
        seen_compact_set.add(compact_phone)
        result_list.append(clean_phone)
    return result_list


def extract_public_phone_token_list(
    text: str,
    include_service: bool = True,
    include_landline: bool = None,
) -> List[str]:
    if include_landline is None:
        include_landline = COLLECT_LANDLINE_PHONE
    phone_list = []
    phone_list.extend(MOBILE_PHONE_PATTERN.findall(text or ""))
    if include_landline:
        phone_list.extend(phone.replace(" ", "") for phone in LANDLINE_PHONE_PATTERN.findall(text or ""))
    if include_service:
        phone_list.extend(phone.replace(" ", "") for phone in SERVICE_PHONE_PATTERN.findall(text or ""))
    return dedupe_public_phone_list(phone_list, include_landline=include_landline)


def split_public_phone_text(
    phone_text: str,
    include_service: bool = True,
    include_landline: bool = None,
) -> List[str]:
    if not phone_text or not any(char.isdigit() for char in str(phone_text)):
        return []
    return extract_public_phone_token_list(
        str(phone_text),
        include_service=include_service,
        include_landline=include_landline,
    )


def clean_public_phone_text(
    phone_text: str,
    include_service: bool = True,
    include_landline: bool = None,
) -> str:
    return "；".join(
        split_public_phone_text(
            phone_text,
            include_service=include_service,
            include_landline=include_landline,
        )
    )


def merge_public_phone_text(
    *phone_text_list: str,
    include_service: bool = True,
    include_landline: bool = None,
) -> str:
    phone_list = []
    for phone_text in phone_text_list:
        phone_list.extend(
            split_public_phone_text(
                phone_text,
                include_service=include_service,
                include_landline=include_landline,
            )
        )
    return "；".join(dedupe_public_phone_list(phone_list, include_landline=include_landline))
