import re


GENERIC_PRODUCT_SUFFIX_MAP = {
    "3C数码": "3C数码产品",
    "服装": "服装产品",
    "化妆品": "化妆品产品",
    "美妆个护": "美妆个护产品",
}
GENERIC_PRODUCT_VALUE_SET = set(GENERIC_PRODUCT_SUFFIX_MAP.values())

NON_PRODUCT_LABEL_PATTERN_LIST = [
    re.compile(r"^[一二三四五六七八九十0-9]+钻工厂$"),
    re.compile(r"^[一二三四五六七八九十0-9]+钻$"),
    re.compile(r"^\d+\s*年$"),
    re.compile(r"^[\u4e00-\u9fa5]{2,6}\s*\d+\s*年$"),
    re.compile(r"^\d+\s*-\s*\d+\s*人$"),
    re.compile(r"^\d+\s*人以下$"),
    re.compile(r"^\d+(?:\.\d+)?\s*(?:m²|㎡|m2|平米|平方米)$", re.IGNORECASE),
    re.compile(r"^(超级工厂|源头工厂|实力商家|诚信通|工厂档案|工厂展厅|找工厂|看工厂)$"),
    re.compile(r"^(工厂|厂家|供应商|制造商|批发|OEM|ODM|代工|加工|供应链)$", re.IGNORECASE),
]

NON_PRODUCT_LOCATION_LABEL_SET = {
    "北京",
    "上海",
    "天津",
    "重庆",
    "西安",
    "衡阳",
    "广州",
    "深圳",
    "东莞",
    "佛山",
    "中山",
    "珠海",
    "惠州",
    "汕头",
    "揭阳",
    "江门",
    "肇庆",
    "清远",
    "潮州",
    "广东",
    "湖南",
    "湖北",
    "浙江",
    "江苏",
    "福建",
    "山东",
    "河南",
    "河北",
    "广西",
    "江西",
    "四川",
}

CLOTHING_BUSINESS_CATEGORY_RULE_LIST = [
    ("服装服饰", ("服装服饰",)),
    ("服饰制造", ("服饰制造",)),
    ("服装制造", ("服装制造", "机织服装制造", "针织或钩针编织服装制造")),
    ("针纺织品", ("针纺织品", "纺织品", "纺织制成品")),
    ("服装辅料", ("服装辅料",)),
    ("鞋帽箱包", ("鞋帽", "箱包")),
    ("皮革制品", ("皮革制品", "皮革")),
    ("床上用品", ("床上用品",)),
    ("服饰", ("服饰",)),
    ("服装", ("服装",)),
    ("手袋箱包", ("手袋",)),
    ("帽子", ("帽、", "帽，", "帽。", "帽；")),
]

THREE_C_BUSINESS_CATEGORY_RULE_LIST = [
    ("充电器", ("充电器",)),
    ("数据线", ("数据线",)),
    ("计算机周边配件", ("计算机周边配件", "计算机软硬件及外围设备", "计算机软硬件及辅助设备")),
    ("通讯数码产品", ("通讯数码产品",)),
    ("智能家电设备", ("智能家电设备", "家用电器")),
    ("电线电缆", ("电线、电缆", "电线电缆", "电缆")),
    ("通讯设备", ("通讯设备", "通信设备", "移动通信设备", "移动终端设备")),
    ("电子产品", ("电子产品",)),
    ("电子元器件", ("电子元器件", "电子元件及组件", "电子器件", "电子专用材料")),
    ("电池", ("电池", "锂离子电池", "镍氢电池")),
    ("集成电路", ("集成电路", "芯片")),
    ("音响设备", ("音响设备",)),
    ("仪器仪表", ("仪器仪表",)),
    ("五金制品", ("五金制品", "五金产品")),
    ("塑胶制品", ("塑胶制品", "塑料制品", "橡胶制品")),
]

CLOTHING_GENERIC_CATEGORY_SET = {"服饰", "服装"}
CLOTHING_SPECIFIC_CATEGORY_SET = {
    "服装服饰",
    "服饰制造",
    "服装制造",
    "针纺织品",
    "服装辅料",
}

KEYWORD_NOISE_TOKEN_LIST = [
    "广东省",
    "广东",
    "广州市",
    "广州",
    "深圳市",
    "深圳",
    "东莞市",
    "东莞",
    "佛山市",
    "佛山",
    "中山市",
    "中山",
    "惠州市",
    "惠州",
    "珠海市",
    "珠海",
    "汕头市",
    "汕头",
    "有限公司",
    "公司",
    "厂家",
    "工厂",
    "生产厂家",
    "源头厂家",
    "供应商",
    "供应链",
    "制造商",
    "制造",
    "生产",
    "批发",
    "代工",
    "加工厂",
    "加工",
    "厂",
    "跨境",
    "外贸",
    "官网",
    "企业名录",
    "联系电话",
    "电话",
    "1688",
]

MEANINGLESS_KEYWORD_PRODUCT_SET = {"3C", "数码", "产品", "工厂", "厂家", "公司", "3C数码", "服装", "化妆品", "美妆个护"}
LIST_CARD_PRODUCT_ONLY_SOURCE_SET = {"alibaba_1688"}


def clean_product_text(value: str) -> str:
    clean_value = re.sub(r"\s+", " ", str(value or "")).strip()
    clean_value = clean_value.strip("，,。.;；、|/\\-_:：[]【】()（）")
    return clean_value[:120]


def is_non_product_label(value: str) -> bool:
    compact_value = re.sub(r"\s+", "", str(value or ""))
    if not compact_value:
        return True
    if compact_value in {re.sub(r"\s+", "", item) for item in GENERIC_PRODUCT_VALUE_SET}:
        return True
    if compact_value in NON_PRODUCT_LOCATION_LABEL_SET:
        return True
    return any(pattern.fullmatch(compact_value) for pattern in NON_PRODUCT_LABEL_PATTERN_LIST)


def industry_product_fallback(industry: str) -> str:
    clean_industry = clean_product_text(industry)
    return GENERIC_PRODUCT_SUFFIX_MAP.get(clean_industry, f"{clean_industry}产品" if clean_industry else "")


def derive_product_from_keyword(source_keyword: str, industry: str) -> str:
    text = clean_product_text(source_keyword)
    if not text:
        return ""
    clean_industry = clean_product_text(industry)
    for token in KEYWORD_NOISE_TOKEN_LIST:
        text = text.replace(token, " ")
    text = re.sub(r"\b(OEM|ODM)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ，,。.;；、|/\\-_:：[]【】()（）")
    candidate_list = [part.strip() for part in re.split(r"[\s,，;；、|/\\]+", text) if part.strip()]
    for candidate in candidate_list:
        candidate = clean_product_text(candidate)
        if len(candidate) < 2:
            continue
        if candidate == clean_industry:
            continue
        if candidate.upper() in MEANINGLESS_KEYWORD_PRODUCT_SET or candidate in MEANINGLESS_KEYWORD_PRODUCT_SET:
            continue
        if is_non_product_label(candidate):
            continue
        return candidate[:80]
    return industry_product_fallback(industry)


def normalize_product_name(product_name: str, industry: str, source_keyword: str = "") -> str:
    clean_name = clean_product_text(product_name)
    clean_industry = clean_product_text(industry)
    if clean_name and clean_name != clean_industry and not is_non_product_label(clean_name):
        return clean_name
    return derive_product_from_keyword(source_keyword, industry) or industry_product_fallback(industry)


def derive_product_from_business_text(business_text: str, industry: str) -> str:
    clean_text = clean_product_text(business_text)
    if not clean_text:
        return ""
    category_list = []
    clean_industry = clean_product_text(industry)
    rule_list = []
    if clean_industry == "服装":
        rule_list = CLOTHING_BUSINESS_CATEGORY_RULE_LIST
    elif clean_industry in {"3C数码", "3C"}:
        rule_list = THREE_C_BUSINESS_CATEGORY_RULE_LIST
    matched_category_list = []
    for rule_index, (category, token_list) in enumerate(rule_list):
        position_list = [clean_text.find(token) for token in token_list if token in clean_text]
        if position_list:
            matched_category_list.append((min(position_list), rule_index, category))
    category_list = [category for _, _, category in sorted(matched_category_list)]
    if clean_industry == "服装" and any(category in CLOTHING_SPECIFIC_CATEGORY_SET for category in category_list):
        category_list = [category for category in category_list if category not in CLOTHING_GENERIC_CATEGORY_SET]
    if not category_list:
        return ""
    return "、".join(category_list[:3])


def repair_product_name_from_public_fields(
    product_name: str,
    industry: str,
    source_keyword: str = "",
    business_scope: str = "",
    registered_address: str = "",
) -> str:
    clean_name = clean_product_text(product_name)
    clean_industry = clean_product_text(industry)
    if clean_name and clean_name != clean_industry and not is_non_product_label(clean_name):
        return clean_name
    business_text = " ".join([business_scope or "", registered_address or ""])
    derived_product = derive_product_from_business_text(business_text, industry)
    if derived_product:
        return derived_product
    return normalize_product_name(product_name, industry, source_keyword)


def repair_product_name_for_source(
    product_name: str,
    industry: str,
    source_keyword: str = "",
    business_scope: str = "",
    registered_address: str = "",
    source_type: str = "",
) -> str:
    clean_name = clean_product_text(product_name)
    clean_industry = clean_product_text(industry)
    if str(source_type or "") in LIST_CARD_PRODUCT_ONLY_SOURCE_SET:
        if clean_name and clean_name != clean_industry and not is_non_product_label(clean_name):
            return clean_name
        return ""
    return repair_product_name_from_public_fields(
        product_name=product_name,
        industry=industry,
        source_keyword=source_keyword,
        business_scope=business_scope,
        registered_address=registered_address,
    )
