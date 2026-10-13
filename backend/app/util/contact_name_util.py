import re


COMMON_CHINESE_SURNAME_SET = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟"
    "平黄和穆萧尹姚邵汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项祝"
    "董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田"
    "胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石"
    "崔吉龚程邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫"
    "乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武"
    "符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙"
    "池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍桑桂濮牛寿通边"
    "扈燕冀浦尚农温别庄晏柴瞿阎连习容向古易廖庾终暨居衡步都耿满弘"
    "匡国文寇广禄阙东殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶"
    "空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)

COMPOUND_CHINESE_SURNAME_TUPLE = (
    "欧阳",
    "太史",
    "端木",
    "上官",
    "司马",
    "东方",
    "独孤",
    "南宫",
    "万俟",
    "闻人",
    "夏侯",
    "诸葛",
    "尉迟",
    "公羊",
    "赫连",
    "澹台",
    "皇甫",
    "宗政",
    "濮阳",
    "公冶",
    "太叔",
    "申屠",
    "公孙",
    "仲孙",
    "轩辕",
    "令狐",
    "钟离",
    "宇文",
    "长孙",
    "慕容",
    "鲜于",
    "闾丘",
    "司徒",
    "司空",
    "亓官",
    "司寇",
    "子车",
    "颛孙",
    "端木",
    "巫马",
    "公西",
    "漆雕",
    "乐正",
    "壤驷",
    "公良",
    "拓跋",
    "夹谷",
    "宰父",
    "谷梁",
    "段干",
    "百里",
    "东郭",
    "南门",
    "呼延",
    "羊舌",
    "微生",
    "梁丘",
    "左丘",
    "东门",
    "西门",
)

CONTACT_ROLE_SUFFIX_PATTERN = re.compile(
    r"(?:先生|女士|经理|厂长|负责人|负责|法人|法定代表人|经营者|投资人|"
    r"业务员|业务|销售|客服|外贸业务|外贸|联系人|联络人|总经理|老板|总监)+$"
)
CONTACT_LABEL_PREFIX_PATTERN = re.compile(
    r"^(?:联系人|联系卖家|业务联系人|销售联系人|联系人员|负责人员|负责人|"
    r"联系人姓名|联络人|法定代表人|法人|经营者|投资人|姓名)[:：\s]*"
)
NON_NAME_TOKEN_TUPLE = (
    "公司",
    "工厂",
    "厂家",
    "企业",
    "商家",
    "店铺",
    "平台",
    "官网",
    "首页",
    "中心",
    "产品",
    "商品",
    "服务",
    "业务",
    "销售",
    "客服",
    "联系",
    "电话",
    "手机",
    "地址",
    "邮箱",
    "网址",
    "采购",
    "供应",
    "供应链",
    "批发",
    "代工",
    "加工",
    "生产",
    "制造",
    "组装",
    "贴牌",
    "验厂",
    "深度",
    "认证",
    "安装",
    "参数",
    "规格",
    "详情",
    "行业",
    "资讯",
    "动态",
    "新闻",
    "文章",
    "博客",
    "未公开",
    "暂无",
    "号码",
    "品组装",
    "工贴牌",
    "先生",
    "女士",
    "经理",
    "厂长",
    "负责人",
    "法人",
    "法定代表人",
    "经营者",
    "投资人",
)
INVALID_CONTACT_NAME_SET = {
    "联系人",
    "联系卖家",
    "业务联系人",
    "销售联系人",
    "联系人员",
    "负责人员",
    "负责人",
    "产销售",
    "深度验厂",
    "验厂",
    "万元",
    "人民币",
    "金额",
    "出资额",
    "认缴",
    "实缴",
    "认缴出资",
    "实缴出资",
    "未公开",
    "暂无",
    "-",
}
CONTACT_ROLE_LABEL_SET = {"法人", "最大股东", "法人/最大股东"}
CONTACT_ROLE_NAME_PATTERN = re.compile(r"^(法人/最大股东|法人|最大股东)[:：]([\u3400-\u9fff·]{2,4})$")
CONTACT_ROLE_LABEL_PATTERN = re.compile(r"(?:^|[；;])\s*(法人/最大股东|法人|最大股东)\s*[:：]")
MALFORMED_CONTACT_ROLE_LABEL_PATTERN = re.compile(r"^(法人/最大股东|法人|最大股东)(?![:：])")
CONTACT_ROLE_SPLIT_PATTERN = re.compile(r"[；;]")
ROLE_NAME_FORBIDDEN_SEPARATOR_PATTERN = re.compile(r"[:：；;]")
ROLE_PERSON_NAME_FORBIDDEN_TOKEN_TUPLE = (
    "先生",
    "女士",
    "经理",
    "厂长",
    "负责人",
    "法人",
    "法定代表人",
    "经营者",
    "投资人",
    "联系人",
    "联络人",
    "主任",
    "总裁",
    "董事",
    "股东",
    "店长",
    "老板",
    "总监",
    "主管",
    "客服",
    "销售",
    "业务",
    "采购",
    "财务",
    "会计",
    "顾问",
    "专员",
    "助理",
)


def clean_contact_name(contact_name: str) -> str:
    clean_name = re.sub(r"\s+", "", contact_name or "").strip(" ：:，,；;。()（）[]【】<>《》")
    clean_name = CONTACT_LABEL_PREFIX_PATTERN.sub("", clean_name)
    clean_name = clean_name.strip(" ：:，,；;。()（）[]【】<>《》")
    clean_name = CONTACT_ROLE_SUFFIX_PATTERN.sub("", clean_name).strip(" ：:，,；;。")
    return clean_name


def has_plausible_chinese_surname(clean_name: str) -> bool:
    if any(clean_name.startswith(surname) for surname in COMPOUND_CHINESE_SURNAME_TUPLE):
        return len(clean_name) >= 3
    return bool(clean_name and clean_name[0] in COMMON_CHINESE_SURNAME_SET)


def is_valid_plain_contact_name(contact_name: str) -> bool:
    clean_name = clean_contact_name(contact_name)
    if not clean_name or clean_name in INVALID_CONTACT_NAME_SET:
        return False
    if any(token in clean_name for token in NON_NAME_TOKEN_TUPLE):
        return False
    if not re.fullmatch(r"[\u3400-\u9fff·]{2,4}", clean_name):
        return False
    return has_plausible_chinese_surname(clean_name)


def has_role_contact_label(contact_name: str) -> bool:
    raw_contact_name = contact_name or ""
    compact_contact_name = re.sub(r"\s+", "", raw_contact_name).strip(" ，,。()（）[]【】<>《》")
    return bool(
        CONTACT_ROLE_LABEL_PATTERN.search(raw_contact_name)
        or CONTACT_ROLE_LABEL_PATTERN.search(compact_contact_name)
    )


def has_malformed_role_contact_label(contact_name: str) -> bool:
    compact_contact_name = re.sub(r"\s+", "", contact_name or "").strip(" ：:，,。()（）[]【】<>《》")
    return bool(MALFORMED_CONTACT_ROLE_LABEL_PATTERN.match(compact_contact_name))


def normalize_role_person_name(raw_name: str) -> str:
    person_name = raw_name or ""
    if not person_name:
        return ""
    if ROLE_NAME_FORBIDDEN_SEPARATOR_PATTERN.search(person_name):
        return ""
    if has_role_contact_label(person_name) or has_malformed_role_contact_label(person_name):
        return ""
    if CONTACT_LABEL_PREFIX_PATTERN.match(person_name):
        return ""
    if any(token in person_name for token in ROLE_PERSON_NAME_FORBIDDEN_TOKEN_TUPLE):
        return ""
    if person_name != clean_contact_name(person_name):
        return ""
    return person_name if is_valid_plain_contact_name(person_name) else ""


def normalize_role_contact_name(contact_name: str) -> str:
    role_contact_name = contact_name or ""
    if not role_contact_name:
        return ""

    normalized_parts = []
    for role_part in CONTACT_ROLE_SPLIT_PATTERN.split(role_contact_name):
        if not role_part:
            return ""

        match = CONTACT_ROLE_NAME_PATTERN.fullmatch(role_part)
        if not match:
            return ""

        role_label, raw_name = match.groups()
        if role_label not in CONTACT_ROLE_LABEL_SET:
            return ""

        clean_name = normalize_role_person_name(raw_name)
        if not clean_name:
            return ""

        normalized_parts.append(f"{role_label}：{clean_name}")

    return "；".join(normalized_parts)


def is_valid_contact_name(contact_name: str) -> bool:
    if normalize_role_contact_name(contact_name):
        return True
    if has_role_contact_label(contact_name) or has_malformed_role_contact_label(contact_name):
        return False
    return is_valid_plain_contact_name(contact_name)


def normalize_contact_name(contact_name: str) -> str:
    role_contact_name = normalize_role_contact_name(contact_name)
    if role_contact_name:
        return role_contact_name
    if has_role_contact_label(contact_name) or has_malformed_role_contact_label(contact_name):
        return ""

    clean_name = clean_contact_name(contact_name)
    if has_role_contact_label(clean_name):
        return ""
    if has_malformed_role_contact_label(clean_name):
        return ""
    return clean_name if is_valid_plain_contact_name(clean_name) else ""
