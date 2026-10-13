GUANGDONG_REGION_TOKEN_LIST = [
    "广东",
    "广东省",
    "广州",
    "广州市",
    "深圳",
    "深圳市",
    "珠海",
    "珠海市",
    "汕头",
    "汕头市",
    "佛山",
    "佛山市",
    "韶关",
    "韶关市",
    "湛江",
    "湛江市",
    "肇庆",
    "肇庆市",
    "江门",
    "江门市",
    "茂名",
    "茂名市",
    "惠州",
    "惠州市",
    "梅州",
    "梅州市",
    "汕尾",
    "汕尾市",
    "河源",
    "河源市",
    "阳江",
    "阳江市",
    "清远",
    "清远市",
    "东莞",
    "东莞市",
    "中山",
    "中山市",
    "潮州",
    "潮州市",
    "揭阳",
    "揭阳市",
    "云浮",
    "云浮市",
]

NON_GUANGDONG_PROVINCE_TOKEN_LIST = [
    "北京",
    "天津",
    "河北",
    "山西",
    "内蒙古",
    "辽宁",
    "吉林",
    "黑龙江",
    "上海",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广西",
    "海南",
    "重庆",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
    "台湾",
]


def is_guangdong_text(text: str) -> bool:
    clean_text = text or ""
    if not clean_text:
        return False
    return any(token in clean_text for token in GUANGDONG_REGION_TOKEN_LIST)


def has_non_guangdong_province_text(text: str) -> bool:
    clean_text = text or ""
    if not clean_text:
        return False
    if is_guangdong_text(clean_text):
        return False
    return any(token in clean_text for token in NON_GUANGDONG_PROVINCE_TOKEN_LIST)
