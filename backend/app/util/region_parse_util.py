import re
from typing import Dict, Iterable, Tuple


REGION_FIELD_DEFAULT = {
    "province": "",
    "city": "",
    "district": "",
    "city_source": "",
    "city_confidence": "",
}

CONFIDENCE_ORDER = {"": 0, "low": 1, "medium": 2, "high": 3}

GUANGDONG_CITY_LIST = [
    "广州",
    "深圳",
    "珠海",
    "汕头",
    "佛山",
    "韶关",
    "湛江",
    "肇庆",
    "江门",
    "茂名",
    "惠州",
    "梅州",
    "汕尾",
    "河源",
    "阳江",
    "清远",
    "东莞",
    "中山",
    "潮州",
    "揭阳",
    "云浮",
]

KNOWN_CITY_PROVINCE_MAP = {city: "广东省" for city in GUANGDONG_CITY_LIST}
KNOWN_CITY_ALIAS_LIST = []
for city in GUANGDONG_CITY_LIST:
    KNOWN_CITY_ALIAS_LIST.extend([city, f"{city}市"])

GUANGDONG_CITY_ENGLISH_ALIAS_MAP = {
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "zhuhai": "珠海",
    "shantou": "汕头",
    "foshan": "佛山",
    "shaoguan": "韶关",
    "zhanjiang": "湛江",
    "zhaoqing": "肇庆",
    "jiangmen": "江门",
    "maoming": "茂名",
    "huizhou": "惠州",
    "meizhou": "梅州",
    "shanwei": "汕尾",
    "heyuan": "河源",
    "yangjiang": "阳江",
    "qingyuan": "清远",
    "dongguan": "东莞",
    "zhongshan": "中山",
    "chaozhou": "潮州",
    "jieyang": "揭阳",
    "yunfu": "云浮",
}

PROVINCE_CITY_PATTERN = re.compile(
    r"(?P<province>[\u4e00-\u9fa5]{2,9}(?:省|自治区))"
    r"[\s,，;；、-]*"
    r"(?P<city>[\u4e00-\u9fa5]{2,5}?市)"
)
GENERAL_CITY_PATTERN = re.compile(r"(?:^|[省自治区\s,，;；、（）()])([\u4e00-\u9fa5]{2,5}?市)")
DISTRICT_PATTERN = re.compile(r"([\u4e00-\u9fa5]{1,12}(?:区|县|市|镇|街道))")


def normalize_city_name(city: str) -> str:
    clean_city = str(city or "").strip()
    if clean_city.endswith("市") and len(clean_city) > 2:
        clean_city = clean_city[:-1]
    return clean_city


def normalize_province_name(province: str, city: str = "") -> str:
    clean_province = str(province or "").strip()
    clean_city = normalize_city_name(city)
    if clean_province:
        return clean_province
    return KNOWN_CITY_PROVINCE_MAP.get(clean_city, "")


def pick_district_after_city(text: str, city: str) -> str:
    clean_text = str(text or "")
    clean_city = normalize_city_name(city)
    if not clean_text or not clean_city:
        return ""
    city_index = clean_text.find(f"{clean_city}市")
    city_token_length = len(clean_city) + 1
    if city_index < 0:
        city_index = clean_text.find(clean_city)
        city_token_length = len(clean_city)
    search_text = clean_text[city_index + city_token_length: city_index + city_token_length + 40] if city_index >= 0 else clean_text[:80]
    match = DISTRICT_PATTERN.search(search_text)
    return match.group(1) if match else ""


def parse_region_from_text(text: str) -> Tuple[str, str, str]:
    clean_text = str(text or "").strip()
    if not clean_text:
        return "", "", ""

    province_match = PROVINCE_CITY_PATTERN.search(clean_text)
    if province_match:
        province = normalize_province_name(province_match.group("province"))
        city = normalize_city_name(province_match.group("city"))
        return province, city, pick_district_after_city(clean_text, city)

    for city_alias in KNOWN_CITY_ALIAS_LIST:
        if city_alias and city_alias in clean_text:
            city = normalize_city_name(city_alias)
            province = normalize_province_name("", city)
            return province, city, pick_district_after_city(clean_text, city)

    for city_alias, city in GUANGDONG_CITY_ENGLISH_ALIAS_MAP.items():
        if re.search(rf"\b{re.escape(city_alias)}\b", clean_text, re.IGNORECASE):
            return normalize_province_name("", city), city, ""

    city_match = GENERAL_CITY_PATTERN.search(clean_text)
    if city_match:
        city = normalize_city_name(city_match.group(1))
        province = normalize_province_name("", city)
        return province, city, pick_district_after_city(clean_text, city)

    return "", "", ""


def iter_region_candidate_texts(
    *,
    registered_address: str = "",
    region_text: str = "",
    company_name: str = "",
    suspected_company_name: str = "",
    source_keyword: str = "",
) -> Iterable[Tuple[str, str, str]]:
    yield registered_address, "注册地址", "high"
    yield region_text, "页面地区", "medium"
    yield company_name, "公司名称", "medium"
    yield suspected_company_name, "疑似公司名", "medium"
    yield source_keyword, "搜索关键词", "low"


def extract_region_info(
    *,
    registered_address: str = "",
    region_text: str = "",
    company_name: str = "",
    suspected_company_name: str = "",
    source_keyword: str = "",
) -> Dict[str, str]:
    for text, source, confidence in iter_region_candidate_texts(
        registered_address=registered_address,
        region_text=region_text,
        company_name=company_name,
        suspected_company_name=suspected_company_name,
        source_keyword=source_keyword,
    ):
        province, city, district = parse_region_from_text(text)
        if city:
            return {
                "province": province,
                "city": city,
                "district": district,
                "city_source": source,
                "city_confidence": confidence,
            }
    return dict(REGION_FIELD_DEFAULT)


def is_better_region_info(new_region: Dict[str, str], old_region: Dict[str, str]) -> bool:
    if not new_region.get("city"):
        return False
    if not old_region.get("city"):
        return True
    return CONFIDENCE_ORDER.get(new_region.get("city_confidence", ""), 0) > CONFIDENCE_ORDER.get(
        old_region.get("city_confidence", ""),
        0,
    )
