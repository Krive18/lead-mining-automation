import re


ADDRESS_STOP_TOKEN_LIST = [
    "法定代表人",
    "经营者",
    "投资人",
    "注册资本",
    "成立日期",
    "登记状态",
    "经营状态",
    "统一社会信用代码",
    "股东",
    "主要人员",
    "变更记录",
    "联系方式",
    "联系电话",
    "电话",
    "手机",
    "邮箱",
    "官网",
    "网址",
    "附近企业",
    "附近公司",
    "地图",
    "风险",
    "经营范围",
    "一般项目",
    "许可项目",
    "依法须经批准",
    "查看动态",
    "企业名称变更",
    "住所变更",
    "地址变更",
    "驻在地址等变更",
    "数据纠错",
    "关注自身",
    "通信地址",
    '"sourceDisplayWeight"',
    '"reportYear"',
    '"longitude"',
    '"latitude"',
    '"fromTime"',
    '"showSource"',
    '"companyOrgType"',
    '"dataUpdateCount"',
    '"dataUpdatedAt"',
    '"errorUpdateCount"',
    '"errorUpdatedAt"',
    '"params"',
    '"gid"',
]

ADDRESS_REQUIRED_TOKEN_PATTERN = re.compile(r"(省|市|区|县|镇|街|路|号|村|园|栋|室|楼|房|座|工业园|开发区)")
JSON_NOISE_PATTERN = re.compile(r'["{}[\]]|dataUpdateCount|dataUpdatedAt|params|gid|longitude|latitude|error')


def clean_registered_address_text(value: str) -> str:
    clean_value = str(value or "").strip()
    if not clean_value:
        return ""
    clean_value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), clean_value)
    change_match = re.search(r"变更为[“\"](?P<address>[^”\"]{6,180})[”\"]", clean_value)
    if change_match:
        clean_value = change_match.group("address")
    clean_value = re.sub(r"\s+", " ", clean_value)
    stop_pattern = "|".join(re.escape(token) for token in ADDRESS_STOP_TOKEN_LIST)
    clean_value = re.split(rf"(?={stop_pattern})", clean_value)[0]
    clean_value = re.sub(r"(附近公司|附近企业)\s*$", "", clean_value)
    clean_value = clean_value.strip(" ：:,，；;。\"'{}[]")
    clean_value = re.sub(r"\s+", "", clean_value)
    if not re.search(r"[\u4e00-\u9fa5]", clean_value):
        return ""
    if JSON_NOISE_PATTERN.search(clean_value):
        return ""
    if not ADDRESS_REQUIRED_TOKEN_PATTERN.search(clean_value):
        return ""
    return clean_value[:180]
