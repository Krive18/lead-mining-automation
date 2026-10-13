import logging
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, quote_from_bytes, quote_plus, urlparse

from app.core.config import get_config
from app.core.constant import (
    SOURCE_TYPE_ALIBABA_1688,
    SOURCE_TYPE_ALIBABA_INTERNATIONAL,
    SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT,
    SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
    SOURCE_TYPE_AI_WEB_SEARCH,
    SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
    SOURCE_TYPE_DOUYIN_QCC,
    SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
    SOURCE_TYPE_QIXIN_PUBLIC_WEB,
    SOURCE_TYPE_QCC_PUBLIC_WEB,
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
)
from app.model.schema import CollectedLeadDTO
from app.service.deepseek_ai_service import DeepSeekAiService
from app.service.web_search_service import PublicPageDocument, PublicWebSearchService, WebSearchResult
from app.util.browser_profile_util import list_browser_profile_process_id
from app.util.contact_name_util import (
    clean_contact_name as clean_public_contact_name,
    is_valid_contact_name as is_valid_public_contact_name,
    normalize_contact_name,
)
from app.util.phone_filter_util import (
    BLOCKED_PHONE_SET,
    LANDLINE_PHONE_PATTERN,
    MOBILE_PHONE_PATTERN,
    SERVICE_PHONE_PATTERN,
    clean_public_phone_text,
    compact_phone_text,
    dedupe_public_phone_list,
    extract_public_phone_token_list,
    is_blocked_phone,
    merge_public_phone_text,
    split_public_phone_text,
)
from app.util.address_util import clean_registered_address_text
from app.util.credit_code_util import extract_unified_social_credit_code as extract_credit_code_from_text
from app.util.region_parse_util import GUANGDONG_CITY_LIST, normalize_city_name
from app.util.region_util import has_non_guangdong_province_text, is_guangdong_text

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None


logger = logging.getLogger(__name__)


def should_wait_for_batch_cooldown(
    collected_count: int,
    collect_limit: int,
    batch_size: int,
    cooldown_seconds: float,
) -> bool:
    if batch_size <= 0 or cooldown_seconds <= 0:
        return False
    if collected_count <= 0 or collected_count >= collect_limit:
        return False
    return collected_count % batch_size == 0


def format_wait_seconds(seconds: float) -> str:
    return f"{seconds:g}"


def sleep_with_jitter(seconds: float, jitter_ratio: float = 0.35, min_seconds: float = 0.0) -> None:
    if seconds <= 0:
        return
    jitter = max(seconds * jitter_ratio, 0)
    wait_seconds = seconds + random.uniform(-jitter, jitter)
    time.sleep(max(min_seconds, wait_seconds))


def build_jittered_milliseconds(milliseconds: int, jitter_ratio: float = 0.35, min_milliseconds: int = 0) -> int:
    if milliseconds <= 0:
        return 0
    jitter = max(milliseconds * jitter_ratio, 0)
    wait_milliseconds = milliseconds + random.uniform(-jitter, jitter)
    return int(max(min_milliseconds, wait_milliseconds))


def wait_for_page_timeout_with_jitter(
    page,
    milliseconds: int,
    jitter_ratio: float = 0.35,
    min_milliseconds: int = 0,
) -> None:
    wait_milliseconds = build_jittered_milliseconds(milliseconds, jitter_ratio, min_milliseconds)
    if wait_milliseconds > 0:
        page.wait_for_timeout(wait_milliseconds)


COMPANY_NAME_PATTERN = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,80}?"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|商行|经营部|工作室|工厂|厂))"
)
INVALID_COMPANY_NAME_SET = {
    "找工厂",
    "找货源",
    "找供应商",
    "找服务",
    "找代发",
    "挑好货",
    "开店",
    "采购车",
    "官方服务",
    "服装工厂",
    "女装工厂",
    "男装工厂",
    "童装工厂",
    "化妆品工厂",
    "护肤品工厂",
    "美妆工厂",
    "手机壳工厂",
    "数据线工厂",
    "耳机工厂",
}
DISQUALIFIED_RISK_TOKEN_LIST: tuple = ()
CONTACT_PATTERN_LIST = [
    re.compile(r"(?:联系人|联系卖家|业务联系人|负责人)[:：\s]*([\u4e00-\u9fa5A-Za-z]{2,12})"),
    re.compile(r"([\u4e00-\u9fa5]\s*[\u4e00-\u9fa5](?:\s*[\u4e00-\u9fa5])?)\s*(?:先生|女士|经理|厂长|负责人|业务)"),
    re.compile(r"([\u4e00-\u9fa5]{2,4})\s*(?:先生|女士|经理|厂长|负责人)"),
    re.compile(r"([\u4e00-\u9fa5]{2,4})(?:先生|女士|经理|厂长)"),
]
CONTACT_EXTRA_PATTERN_LIST = [
    re.compile(r"(?:联系人|联系卖家|业务联系人|销售联系人|联系人员|负责人员|负责人|联系人姓名)[:：\s]*([\u4e00-\u9fa5A-Za-z·]{2,20})"),
    re.compile(r"(?:法定代表人|经营者|投资人)[:：\s]*([\u4e00-\u9fa5A-Za-z·]{2,20})"),
    re.compile(r"([\u4e00-\u9fa5]{2,4})\s*(?:业务员|业务|销售|客服|外贸业务|外贸|厂长|负责人|经理|先生|女士)"),
    re.compile(r"([\u4e00-\u9fa5]\s*[\u4e00-\u9fa5](?:\s*[\u4e00-\u9fa5])?)\s*(?:先生|女士|经理|厂长|负责人|业务|业务员|销售|客服|外贸业务|外贸)"),
]
CONTACT_ROLE_SUFFIX_PATTERN = re.compile(r"(?:业务员|业务|销售|客服|外贸业务|外贸|厂长|负责人|负责|经理|先生|女士|法人|法定代表人|经营者|投资人)+$")
INVALID_CONTACT_NAME_SET = {
    "联系人",
    "联系卖家",
    "业务联系人",
    "销售联系人",
    "联系人员",
    "负责人员",
    "负责人",
    "电话联系",
    "在线沟通",
    "立即询价",
    "采购车",
    "消息",
    "登录",
    "注册",
    "手机阿里",
    "有限公司",
    "有限责任",
    "股份有限公司",
    "个人独资",
    "合伙企业",
    "未公开",
    "暂无",
    "支持",
    "官网",
    "云官网",
    "首页",
    "产品",
    "平台",
    "中心",
    "客户",
    "合作",
    "咨询",
    "顾问",
    "服务",
    "关于",
    "生产",
    "制造",
    "安装",
    "认证",
    "点击",
    "免费",
    "行业",
    "资讯",
    "动态",
    "新闻",
    "文章",
    "博客",
    "腾集",
}
STRICT_CONTACT_LABEL_PATTERN_LIST = [
    re.compile(
        r"(?:联系人|联系卖家|业务联系人|销售联系人|联系人员|负责人员|负责人|"
        r"联系人姓名|联络人|业务员|销售代表|外贸业务|外贸联系人|客服联系人)"
        r"[:：\s]*(?!电话|手机|地址|邮箱|网址|QQ|微信)([\u4e00-\u9fa5A-Za-z·]{2,6})"
    ),
    re.compile(r"(?:法定代表人|经营者|投资人)[:：\s]*([\u4e00-\u9fa5A-Za-z·]{2,12})"),
]
STRICT_CONTACT_TITLE_PATTERN_LIST = [
    re.compile(r"([\u4e00-\u9fa5]{1,3}(?:先生|女士|经理|厂长|负责人))"),
]
BUSINESS_KEYWORD_LIST = [
    "工厂",
    "厂家",
    "厂",
    "批发",
    "批发商",
    "源头",
    "OEM",
    "ODM",
    "代工",
    "供应链",
    "供应商",
    "生产",
    "制造",
    "加工",
    "定制",
    "现货",
    "外贸",
    "跨境",
]
AI_WEB_PLATFORM_COMPANY_TOKEN_LIST = (
    "腾讯",
    "阿里巴巴",
    "百度",
    "字节跳动",
    "网易",
    "京东",
    "美团",
    "滴滴",
    "快手",
    "拼多多",
)
AI_WEB_SUPPLIER_INTENT_TOKEN_LIST = (
    "工厂",
    "厂家",
    "厂",
    "批发",
    "批发商",
    "供应链",
    "供应商",
    "生产",
    "制造",
    "OEM",
    "ODM",
    "代工",
    "加工",
    "定制",
    "源头",
    "现货",
    "外贸",
    "跨境",
)
AI_WEB_CATEGORY_EVIDENCE_KEYWORD_MAP = {
    "3C数码": [
        "3C",
        "数码",
        "电子产品",
        "电子元器件",
        "电子配件",
        "手机壳",
        "手机配件",
        "数据线",
        "充电器",
        "耳机",
        "蓝牙",
        "移动电源",
        "电源适配器",
        "智能穿戴",
        "数码配件",
        "电脑配件",
        "平板配件",
        "通讯设备",
        "通信设备",
    ],
}
AI_WEB_SPECIFIC_CATEGORY_KEYWORD_MAP = {
    "3C数码": [
        "电子产品",
        "电子元器件",
        "电子配件",
        "手机壳",
        "手机配件",
        "数据线",
        "充电器",
        "耳机",
        "蓝牙耳机",
        "移动电源",
        "电源适配器",
        "智能穿戴",
        "数码配件",
        "电脑配件",
        "平板配件",
        "通讯设备",
        "通信设备",
        "Type-C",
        "TYPE-C",
    ],
    "服装": [
        "服装",
        "服饰",
        "女装",
        "男装",
        "童装",
        "内衣",
        "制衣",
        "成衣",
        "面料",
        "辅料",
        "纺织",
        "针织",
        "梭织",
    ],
    "美妆个护": [
        "化妆品",
        "护肤",
        "护肤品",
        "美妆",
        "彩妆",
        "美甲",
        "甲油胶",
        "穿戴甲",
        "美甲产品",
        "美甲工具",
        "面膜",
        "日化",
        "洗护",
        "香水",
        "精华",
        "乳液",
        "膏霜",
        "口红",
        "粉底",
        "洁面",
    ],
}
AI_WEB_NON_TARGET_COMPANY_TOKEN_MAP = {
    "3C数码": [
        "包装",
        "仓库",
        "仓储",
        "物流",
        "货运",
        "供应链服务",
        "网络",
        "软件",
        "信息系统",
        "计算机系统",
    ],
    "服装": [
        "包装",
        "仓库",
        "仓储",
        "物流",
        "货运",
        "网络",
        "软件",
        "信息系统",
        "文化",
        "传媒",
        "广告",
        "咨询",
    ],
    "美妆个护": [
        "包装",
        "仓库",
        "仓储",
        "物流",
        "货运",
        "网络",
        "软件",
        "信息系统",
        "文化",
        "传媒",
        "广告",
        "咨询",
    ],
}
AI_WEB_TRUSTED_SUPPLIER_HOST_TOKEN_LIST = (
    "1688.com",
    "aiqicha.baidu.com",
    "qcc.com",
    "qixin.com",
    "tianyancha.com",
    "11467.com",
    "shunqi.com",
    "makepolo.com",
    "huangye88.com",
)
AI_WEB_LOW_VALUE_HOST_TOKEN_LIST = (
    "baike.baidu.com",
    "zhihu.com",
    "wikipedia.org",
    "gov.cn",
    "stats.gov.cn",
    "sz.gov.cn",
    "dg.gov.cn",
    "jobui.com/rank",
    "so.com",
    "sogou.com",
)
AI_WEB_LOW_VALUE_TEXT_TOKEN_LIST = (
    "百度百科",
    "知乎专栏",
    "政府门户",
    "人民政府",
    "统计局",
    "排行榜",
    "公司排名",
)
NON_GUANGDONG_REGION_PREFIX_LIST = (
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
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
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
    "西藏",
    "内蒙古",
    "香港",
    "澳门",
    "台湾",
    "苏州",
    "杭州",
    "宁波",
    "温州",
    "泉州",
    "厦门",
    "成都",
    "武汉",
    "长沙",
    "郑州",
    "青岛",
)
BLOCKED_URL_TOKEN_LIST = ["login.1688.com", "passport.1688.com", "login.taobao.com", "sec.1688.com"]
ALIBABA_1688_LOGIN_URL = "https://login.1688.com/member/signin.htm"
BLOCKED_TEXT_TOKEN_LIST = [
    "请完成验证",
    "安全验证",
    "拖动滑块",
    "请拖动下方滑块完成验证",
    "通过验证以确保正常访问",
    "访问被拒绝",
    "亲，访问被拒绝",
    "身份验证以继续使用",
    "点击按钮开始验证",
]
FEEDBACK_TEXT_TOKEN_LIST = ["遇到问题", "请选择问题类型", "看不见验证码", "频繁看到该验证码", "提交成功，感谢反馈"]
FEEDBACK_PAGE_MESSAGE = "1688进入验证异常反馈页，该页面不是验证码；请在打开的浏览器中手动回到1688首页或搜索结果页，系统会等待页面恢复"
PROFILE_BUSY_MESSAGE = "1688采集专用浏览器资料目录正在被占用，请先关闭预热/采集浏览器后再启动任务"
MOJIBAKE_TOKEN_LIST = [
    "�",
    "ï¿½",
    "锟",
    "斤拷",
    "茂驴陆",
    "閿",
    "閲",
    "楠",
    "鐢",
    "鑱",
    "绾",
    "鍏",
    "涓",
    "宸",
    "囚",
    "ョ",
    "链将囚",
    "ョ配",
    "宸ャ",
    "将囚",
]
DETAIL_PAGE_TOKEN_LIST = ["综合概览", "工厂店", "工厂展厅", "工厂档案", "电话联系", "立即询价"]
ALIBABA_1688_RESULT_SKIP_TEXT_TOKEN_LIST = [
    "首页",
    "我的阿里",
    "下载插件",
    "我的订单",
    "采购车",
    "消息",
    "官方服务",
    "开店",
    "简体中文",
    "以图搜款",
    "找货源",
    "找供应商",
    "工业品",
    "找服务",
    "找代发",
    "批量询价",
    "在线沟通",
    "立即询价",
    "实力榜",
    "服务榜",
    "采购助手",
]
ALIBABA_1688_CANDIDATE_DENY_URL_TOKEN_LIST = [
    "offer/",
    "offer_search",
    "selloffer",
    "factory_search",
    "detail.1688.com",
    "login",
    "passport",
    "cart",
    "purchase",
    "trade",
    "message",
    "order",
    "favorite",
    "service",
    "plugin",
    "market",
    "activity",
]
GENERIC_1688_KEYWORD_TOKEN_LIST = [
    "工厂",
    "厂家",
    "厂",
    "批发",
    "供应链",
    "跨境",
    "OEM",
    "ODM",
    "代工",
    "加工",
    "广东",
    "广州",
    "深圳",
    "东莞",
    "佛山",
    "清远",
    "中山",
    "珠海",
    "惠州",
]
ALIBABA_1688_KEYWORD_AFFINITY_GROUP_LIST = [
    (
        ("手持蒸汽熨烫机", "蒸汽熨烫机", "手持挂烫机", "挂烫机"),
        ("手持蒸汽熨烫机", "蒸汽熨烫机", "手持挂烫机", "挂烫机"),
    ),
    (
        ("游戏手柄", "无线游戏手柄", "蓝牙游戏手柄", "电竞手柄"),
        ("游戏手柄", "无线游戏手柄", "蓝牙游戏手柄", "蓝牙手柄", "电竞手柄"),
    ),
    (
        ("游戏键盘", "电竞键盘", "机械键盘"),
        ("游戏键盘", "电竞键盘", "机械键盘", "键盘", "键鼠套装"),
    ),
    (
        ("游戏鼠标", "电竞鼠标", "有线鼠标", "无线鼠标"),
        ("游戏鼠标", "电竞鼠标", "有线鼠标", "无线鼠标", "鼠标", "键鼠套装"),
    ),
    (
        ("游戏耳机", "电竞耳机", "头戴式耳机", "耳麦"),
        ("游戏耳机", "电竞耳机", "头戴式耳机", "耳麦", "耳机"),
    ),
    (
        ("美甲", "甲油胶", "穿戴甲", "指甲油", "光疗胶", "甲片", "甲胶", "卸甲"),
        ("美甲", "甲油胶", "穿戴甲", "指甲油", "光疗胶", "甲片", "甲胶", "卸甲", "美甲工具"),
    ),
    (
        ("护肤", "面膜", "精华", "乳液", "膏霜", "洁面", "爽肤", "面霜"),
        ("护肤", "护肤品", "面膜", "精华", "乳液", "膏霜", "洁面", "爽肤", "面霜"),
    ),
    (
        ("彩妆", "口红", "粉底", "眼影", "腮红"),
        ("彩妆", "口红", "粉底", "眼影", "腮红", "唇釉", "眉笔"),
    ),
    (
        ("睫毛", "假睫毛", "接睫毛"),
        ("睫毛", "假睫毛", "接睫毛", "睫毛工具"),
    ),
    (
        ("防晒", "防晒霜", "防晒膏", "防晒喷雾"),
        ("防晒", "防晒霜", "防晒膏", "防晒喷雾"),
    ),
    (
        ("化妆刷", "美妆蛋", "粉扑", "美妆工具"),
        ("化妆刷", "美妆蛋", "粉扑", "洗脸扑", "美妆工具"),
    ),
    (
        ("洗发水", "护发素", "沐浴露", "洗护套装"),
        ("洗发", "护发", "沐浴", "洗护套装", "洗发水", "护发素", "沐浴露"),
    ),
    (
        ("手机壳", "保护壳", "手机保护套"),
        ("手机壳", "保护壳", "手机保护套", "iPhone保护套", "手机套"),
    ),
    (
        ("数据线", "充电线", "Type-C", "TYPE-C"),
        ("数据线", "充电线", "Type-C", "TYPE-C", "线材"),
    ),
    (
        ("充电器", "电源适配器"),
        ("充电器", "电源适配器", "快充", "充电头"),
    ),
    (
        ("耳机", "蓝牙耳机"),
        ("耳机", "蓝牙耳机", "耳麦"),
    ),
    (
        ("蓝牙音响", "蓝牙音箱", "音响", "音箱"),
        ("蓝牙音响", "蓝牙音箱", "音响", "音箱", "喇叭"),
    ),
    (
        ("手机支架", "车载支架", "车载手机支架"),
        ("手机支架", "车载支架", "车载手机支架", "自拍杆"),
    ),
    (
        ("手机保护膜", "手机镜头膜", "贴膜", "保护膜"),
        ("手机保护膜", "手机镜头膜", "贴膜", "保护膜", "钢化膜"),
    ),
    (
        ("女装", "连衣裙", "女式T恤"),
        ("女装", "连衣裙", "女式T恤", "半身裙", "女裤", "女士上衣", "大码女装"),
    ),
    (
        ("男装", "男式T恤"),
        ("男装", "男式T恤", "男裤", "男士上衣"),
    ),
    (
        ("童装", "儿童服装"),
        ("童装", "儿童服装", "童裤", "童裙", "儿童套装"),
    ),
]
ALIBABA_1688_BROAD_KEYWORD_SET = {
    "服装",
    "服饰",
    "3C",
    "3C数码",
    "数码",
    "电子",
    "电子产品",
    "科技",
    "美妆",
    "美妆个护",
    "化妆品",
    "日化",
    "洗护",
}
ALIBABA_1688_MAX_SEARCH_PAGE_COUNT = 50
ALIBABA_1688_DYNAMIC_SEARCH_PAGE_CAP = 30
ALIBABA_1688_EMPTY_CANDIDATE_PAGE_STOP_COUNT = 3
ALIBABA_1688_REPEATED_PAGE_STOP_COUNT = 2
ALIBABA_1688_REPEATED_PAGE_OVERLAP_RATIO = 0.7
MADE_IN_CHINA_MAX_SEARCH_PAGE_COUNT = 5
MADE_IN_CHINA_BLOCKED_TEXT_TOKEN_LIST = [
    "请完成验证",
    "安全验证",
    "请输入验证码",
    "访问过于频繁",
    "访问被拒绝",
    "登录后继续",
]
MADE_IN_CHINA_SKIP_TEXT_TOKEN_LIST = [
    "中国制造网",
    "Made-in-China",
    "首页",
    "产品信息",
    "公司信息",
    "采购信息",
    "热门产品",
    "发布询价单",
    "在线交谈",
    "发联系信",
    "查看更多公司信息",
    "免费订阅",
    "登录",
    "注册",
]
MADE_IN_CHINA_PROFILE_HOST_SUFFIX_LIST = (".cn.made-in-china.com", ".made-in-china.com")
PRIORITY_GUANGDONG_CITY_LIST = ["广州", "深圳", "东莞", "佛山", "惠州", "中山", "珠海", "清远"]
DEFAULT_GUANGDONG_TARGET_CITY = "广东省"
GUANGDONG_PRIORITY_PREFIX_LIST = [
    "广州",
    "清远",
    "东莞",
    "佛山",
    "广东",
    "深圳",
    "中山",
    "珠海",
    "惠州",
    "汕头",
    "江门",
]
PUBLIC_WEB_SEARCH_KEYWORD_LIMIT = 80
INDUSTRY_PUBLIC_SEARCH_KEYWORD_MAP = {
    "服装": [
        "服装厂",
        "服装批发",
        "服装OEM",
        "女装批发",
        "服饰供应链",
        "制衣厂",
        "女装工厂",
        "服装加工厂",
        "跨境服装供应链",
    ],
    "3C数码": [
        "电子产品",
        "手机配件",
        "手机壳",
        "数据线",
        "耳机",
        "数据线OEM",
        "Type-C数据线",
        "充电器OEM",
        "移动电源工厂",
        "蓝牙耳机工厂",
        "3C配件工厂",
        "数码配件批发",
    ],
    "美妆个护": [
        "化妆品",
        "化妆品工厂",
        "化妆品OEM",
        "护肤品OEM",
        "美妆供应链",
        "美甲产品",
        "甲油胶",
        "穿戴甲",
        "彩妆代工",
        "日化工厂",
        "面膜OEM",
    ],
}
INDUSTRY_RELEVANCE_KEYWORD_MAP = {
    "服装": [
        "服装",
        "服饰",
        "女装",
        "男装",
        "童装",
        "内衣",
        "鞋",
        "鞋帽",
        "箱包",
        "皮具",
        "纺织",
        "针织",
        "梭织",
        "制衣",
        "成衣",
        "连衣裙",
        "T恤",
        "女式T恤",
        "大码",
        "衬衫",
        "卫衣",
        "家居服",
        "睡裙",
        "浴袍",
        "内裤",
        "休闲裤",
        "运动套装",
        "面料",
        "辅料",
        "纺织服装",
    ],
    "3C数码": [
        "3C",
        "数码",
        "电子产品",
        "电子元器件",
        "手机",
        "手机壳",
        "手机配件",
        "数据线",
        "充电器",
        "耳机",
        "蓝牙",
        "电源",
        "智能穿戴",
        "通讯设备",
        "通信设备",
        "电脑",
        "平板",
    ],
    "美妆个护": [
        "化妆品",
        "护肤",
        "美妆",
        "彩妆",
        "美甲",
        "甲油胶",
        "穿戴甲",
        "美甲产品",
        "美甲工具",
        "指甲油",
        "光疗胶",
        "面膜",
        "香水",
        "日化",
        "洗护",
        "精华",
        "乳液",
        "膏霜",
        "口红",
        "粉底",
        "洁面",
        "美容",
        "睫毛",
        "假睫毛",
        "接睫毛",
        "化妆刷",
        "美妆蛋",
        "粉扑",
        "防晒",
        "洗发",
        "护发",
        "沐浴",
    ],
}
INDUSTRY_STRONG_RELEVANCE_KEYWORD_MAP = {
    "服装": [
        "服装制造",
        "服饰制造",
        "服装服饰批发",
        "针纺织品",
        "纺织服装",
        "制衣",
        "服装辅料",
        "面料",
        "鞋帽批发",
        "鞋制造",
        "箱包制造",
        "皮革制品",
    ],
    "3C数码": [
        "电子产品",
        "电子元器件",
        "通讯设备",
        "通信设备",
        "手机配件",
        "数据线",
        "充电器",
        "耳机",
        "智能穿戴",
        "计算机软硬件",
        "电源",
    ],
    "美妆个护": [
        "化妆品",
        "护肤品",
        "彩妆",
        "美妆",
        "美甲",
        "甲油胶",
        "穿戴甲",
        "美甲产品",
        "美甲工具",
        "指甲油",
        "光疗胶",
        "日化",
        "洗护",
        "面膜",
        "香水",
        "美容产品",
        "个人护理",
        "睫毛",
        "假睫毛",
        "接睫毛",
        "化妆刷",
        "美妆蛋",
        "粉扑",
        "防晒",
        "洗发",
        "护发",
        "沐浴",
    ],
}
PUBLIC_BUSINESS_LABEL_LIST = [
    "经营范围",
    "一般项目",
    "许可项目",
    "主营产品",
    "主营",
    "产品",
    "国标行业",
    "所属行业",
    "行业",
    "企业简介",
    "基本信息",
]
PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST = [
    "科技",
    "信息",
    "网络",
    "软件",
    "文化",
    "传媒",
    "动漫",
    "广告",
    "空间",
    "咨询",
    "管理",
    "投资",
]
GENERIC_COMPANY_NAME_SET = {
    "有限公司",
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "合伙企业",
    "个人独资企业",
    "分公司",
    "工厂",
    "厂",
    "商行",
    "经营部",
    "工作室",
}
INVALID_PUBLIC_COMPANY_TOKEN_LIST = [
    "企查查",
    "美亚",
    "风鸟",
    "登录",
    "注册",
    "搜索",
    "查询",
    "风险",
    "验证码",
    "企业简介",
    "企业名称",
    "省份地区",
    "已选条件",
    "保存",
    "清除",
    "查看",
    "为您找到",
    "暂无",
    "电话",
    "邮箱",
    "地址",
    "经营范围",
    "法定代表人",
    "报告",
    "下载",
]
KEYWORD_ONLY_COMPANY_PATTERN = re.compile(
    r"^(?:广东|广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|潮州|揭阳|江门|肇庆|"
    r"湛江|茂名|阳江|清远|韶关|梅州|河源|汕尾|云浮)?(?:省|市|区|县)?"
    r"(?:服装|女装|男装|童装|内衣|鞋|鞋业|手机壳|数据线|耳机|充电器|数码|"
    r"3C|化妆品|护肤品|美妆|彩妆|美甲|甲油胶|穿戴甲|指甲油|面膜|日化)"
    r"(?:(?:工厂|厂|厂家|批发|供应链|OEM|ODM|代工|加工|加工厂|生产厂家|源头厂家))*"
    r"(?:有限公司)?$",
    re.IGNORECASE,
)
REAL_COMPANY_STRONG_SUFFIX_TUPLE = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "合伙企业",
    "个人独资企业",
    "分公司",
    "商行",
    "经营部",
    "工作室",
)
FACTORY_COMPANY_SUFFIX_TUPLE = ("工厂", "厂")
GENERIC_FACTORY_NAME_TOKEN_LIST = (
    "OEM",
    "ODM",
    "代工",
    "加工",
    "批发",
    "厂家",
    "供应商",
    "供应链",
    "源头",
    "生产",
    "制造",
)
DETAILED_LOCATION_TOKEN_LIST = (
    "区",
    "县",
    "镇",
    "街道",
    "街",
    "村",
    "工业区",
    "工业园",
    "产业园",
    "科技园",
    "开发区",
)


def clean_company_name_text(company_name: str) -> str:
    clean_name = re.sub(r"\s+", "", company_name or "")
    clean_name = clean_name.strip(" ：:，,；;。()（）[]【】")
    if clean_name.count("(") != clean_name.count(")") or clean_name.count("（") != clean_name.count("）"):
        return ""
    ranking_candidate = re.sub(
        r"^.*?(?:热度榜|实力榜|服务榜|新晋榜|飙升榜|排行榜|榜单)(?:第?\d+名)?",
        "",
        clean_name,
    )
    if ranking_candidate and COMPANY_NAME_PATTERN.search(ranking_candidate):
        clean_name = ranking_candidate.strip(" ：:，,；;。()（）[]【】")
    search_prefix_candidate = re.sub(r"^(?:搜索|查询|查公司|找工厂|找供应商|找货源)+", "", clean_name)
    if search_prefix_candidate and COMPANY_NAME_PATTERN.search(search_prefix_candidate):
        clean_name = search_prefix_candidate.strip(" ：:，,；;。()（）[]【】")
    guangdong_company_pattern = re.compile(
        r"((?:广东省?|广州市?|深圳市?|东莞市?|佛山市?|中山市?|珠海市?|惠州市?|"
        r"汕头市?|潮州市?|揭阳市?|江门市?|肇庆市?|湛江市?|茂名市?|阳江市?|"
        r"清远市?|韶关市?|梅州市?|河源市?|汕尾市?|云浮市?)"
        r"[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,80}?"
        r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|商行|经营部|工作室|工厂|厂))"
    )
    match_list = guangdong_company_pattern.findall(clean_name)
    if match_list:
        return match_list[-1].strip(" ：:，,；;。()（）[]【】")
    return clean_name


def clean_contact_name(contact_name: str) -> str:
    return clean_public_contact_name(contact_name)


def is_valid_contact_name(contact_name: str) -> bool:
    return is_valid_public_contact_name(contact_name)


def extract_contact_name_by_pattern(text: str) -> str:
    for pattern in CONTACT_EXTRA_PATTERN_LIST + CONTACT_PATTERN_LIST:
        match = pattern.search(text or "")
        if not match:
            continue
        contact_name = clean_contact_name(match.group(1))
        if is_valid_contact_name(contact_name):
            return contact_name
    return ""


def extract_strict_contact_name_by_pattern(text: str) -> str:
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if not clean_text:
        return ""
    for pattern in STRICT_CONTACT_LABEL_PATTERN_LIST:
        match = pattern.search(clean_text)
        if not match:
            continue
        contact_name = clean_contact_name(match.group(1))
        if is_valid_contact_name(contact_name):
            return contact_name
    if not has_any_token(clean_text, ("联系人", "联系电话", "电话", "手机", "负责人", "先生", "女士", "经理", "厂长")):
        return ""
    for pattern in STRICT_CONTACT_TITLE_PATTERN_LIST:
        match = pattern.search(clean_text)
        if not match:
            continue
        contact_name = clean_contact_name(match.group(1))
        if is_valid_contact_name(contact_name):
            return contact_name
    return ""


def is_valid_enterprise_name(company_name: str, invalid_token_list: List[str]) -> bool:
    clean_name = clean_company_name_text(company_name)
    if len(clean_name) < 6 or len(clean_name) > 80:
        return False
    if clean_name in GENERIC_COMPANY_NAME_SET or clean_name in INVALID_COMPANY_NAME_SET:
        return False
    if clean_name.startswith(tuple(GENERIC_COMPANY_NAME_SET)):
        return False
    token_list = INVALID_PUBLIC_COMPANY_TOKEN_LIST + invalid_token_list
    if any(token in clean_name for token in token_list):
        return False
    if re.search(r"(省|市|区|县|镇|街道)[)）]", clean_name):
        return False
    if clean_name.count("(") != clean_name.count(")") or clean_name.count("（") != clean_name.count("）"):
        return False
    if KEYWORD_ONLY_COMPANY_PATTERN.fullmatch(clean_name):
        return False
    if re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9]{0,6}(工厂|厂|批发|供应链|OEM|ODM|代工|加工)", clean_name):
        return False
    if clean_name.endswith(("厂", "商行", "经营部", "工作室")) and len(clean_name) < 7:
        return False
    return True


def has_public_phone_text(phone_text: str) -> bool:
    return bool(clean_public_phone_text(phone_text, include_service=True))


def has_disqualified_phone(phone_text: str) -> bool:
    if not phone_text:
        return False
    raw_phone_list = []
    raw_phone_list.extend(MOBILE_PHONE_PATTERN.findall(phone_text))
    raw_phone_list.extend(LANDLINE_PHONE_PATTERN.findall(phone_text))
    raw_phone_list.extend(SERVICE_PHONE_PATTERN.findall(phone_text))
    return any(is_blocked_phone(phone) for phone in raw_phone_list)


def get_disqualified_text_reason(text: str) -> str:
    clean_text = text or ""
    inactive_status = extract_public_company_status_text(clean_text)
    if is_inactive_company_status(inactive_status):
        return f"企业状态为非正常：{inactive_status}"
    if has_inactive_company_banner_text(clean_text):
        return "企业状态为非正常：注销/吊销/迁出"
    return ""


def get_disqualified_lead_reason(lead: CollectedLeadDTO) -> str:
    text = " ".join(
        [
            lead.suspected_company_name,
            lead.company_status,
            lead.risk_tag,
            lead.business_scope,
            lead.registered_address,
            lead.region_text,
            lead.product_name,
        ]
    )
    return get_disqualified_text_reason(text)


def is_disqualified_public_lead(lead: CollectedLeadDTO) -> bool:
    return bool(get_disqualified_lead_reason(lead))


INACTIVE_COMPANY_STATUS_TOKEN_LIST = ["注销", "吊销", "迁出", "停业", "清算", "歇业", "撤销", "责令关闭"]


def extract_public_company_status_text(text: str) -> str:
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if not clean_text:
        return ""
    label_match = re.search(
        r"(?:登记状态|经营状态|企业状态|状态)[:：\s]*"
        r"(存续|在业|开业|正常|注销|吊销|迁出|迁入|停业|清算|歇业|撤销|责令关闭)",
        clean_text,
    )
    if label_match:
        return label_match.group(1).strip()
    banner_match = re.search(
        r"(?:已于\s*)?\d{4}[-./年]\d{1,2}[-./月]\d{1,2}(?:日)?\s*"
        r"(注销|吊销|迁出|停业|清算|歇业|撤销)",
        clean_text[:1200],
    )
    if banner_match:
        return banner_match.group(1).strip()
    leading_text = clean_text[:800]
    inactive_match = re.search(
        r"(?<!未)(注销|吊销|迁出|停业|清算|歇业|撤销)(?:\s|$|曾用名|变更提醒|风险|经营异常|严重违法)",
        leading_text,
    )
    if inactive_match:
        return inactive_match.group(1).strip()
    active_match = re.search(r"(?<![未不])(存续|在业|开业|正常|迁入)", leading_text)
    return active_match.group(1).strip() if active_match else ""


def is_inactive_company_status(status_text: str) -> bool:
    return any(token in (status_text or "") for token in INACTIVE_COMPANY_STATUS_TOKEN_LIST)


def has_inactive_company_banner_text(text: str) -> bool:
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if not clean_text:
        return False
    return bool(
        re.search(
            r"(?:已于\s*)?\d{4}[-./年]\d{1,2}[-./月]\d{1,2}(?:日)?\s*"
            r"(注销|吊销|迁出|停业|清算|歇业|撤销)",
            clean_text[:1200],
        )
    )


def is_active_public_company_lead(lead: CollectedLeadDTO) -> bool:
    if is_inactive_company_status(lead.company_status):
        return False
    return not has_inactive_company_banner_text(lead.region_text)


def is_reliable_guangdong_address(address_text: str) -> bool:
    if not address_text or not is_guangdong_text(address_text):
        return False
    if any(token in address_text for token in ("省份地区", "已选条件", "保存", "清除", "查看", "为您找到")):
        return False
    return any(token in address_text for token in ("市", "区", "县", "镇", "街", "路", "号", "村", "园", "栋", "室"))


def is_reliable_guangdong_public_lead(lead: CollectedLeadDTO) -> bool:
    if is_guangdong_text(lead.suspected_company_name):
        return True
    if is_reliable_guangdong_address(lead.registered_address):
        return True
    if lead.registered_address:
        return False
    return False


def has_any_token(text: str, token_list: List[str]) -> bool:
    return any(token and token in text for token in token_list)


def extract_public_labeled_business_text(text: str) -> str:
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if not clean_text:
        return ""
    field_text_list = []
    stop_pattern = (
        r"(?=统一社会信用代码|法定代表人|经营者|投资人|负责人|注册资本|成立日期|登记状态|"
        r"经营状态|电话|邮箱|网址|地址|住所|企业规模|员工人数|风险|报告|监控|工商信息|"
        r"变更记录|股东|主要人员|历史信息|知识产权|法律诉讼)"
    )
    for label in PUBLIC_BUSINESS_LABEL_LIST:
        pattern = re.compile(rf"{re.escape(label)}[:：\s]*([^。；;\n]{{2,360}})")
        for match in pattern.finditer(clean_text):
            value = re.split(stop_pattern, match.group(1))[0]
            value = value.strip(" ：:，,；;。")
            if value and value not in field_text_list:
                field_text_list.append(value)
    return " ".join(field_text_list)


def is_source_keyword_fallback_product(product_name: str, source_keyword: str, industry: str) -> bool:
    clean_product_name = re.sub(r"\s+", "", product_name or "")
    clean_source_keyword = re.sub(r"\s+", "", source_keyword or "")
    if not clean_product_name:
        return True
    if clean_product_name == re.sub(r"\s+", "", industry or ""):
        return True
    if clean_source_keyword and clean_product_name == clean_source_keyword[: len(clean_product_name)]:
        return True
    return any(
        clean_product_name == re.sub(r"\s+", "", keyword)
        for keyword in split_public_search_keyword(source_keyword)
    )


def is_industry_relevant_public_lead(lead: CollectedLeadDTO) -> bool:
    industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(lead.industry, [lead.industry])
    strong_token_list = INDUSTRY_STRONG_RELEVANCE_KEYWORD_MAP.get(lead.industry, industry_token_list)
    company_name = clean_company_name_text(lead.suspected_company_name)
    business_scope = lead.business_scope or ""
    labeled_business_text = extract_public_labeled_business_text(lead.region_text)
    product_name = "" if is_source_keyword_fallback_product(
        lead.product_name,
        lead.source_keyword,
        lead.industry,
    ) else lead.product_name
    structured_text = " ".join([company_name, business_scope, labeled_business_text, product_name])
    if not has_any_token(structured_text, industry_token_list):
        return False
    if has_any_token(company_name, industry_token_list):
        return True
    if has_any_token(" ".join([business_scope, labeled_business_text, product_name]), strong_token_list):
        return True
    if not has_any_token(company_name, PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST):
        return has_any_token(" ".join([business_scope, labeled_business_text, product_name]), industry_token_list)
    return False


def split_public_search_keyword(keyword_text: str) -> List[str]:
    raw_keyword = (keyword_text or "").strip()
    if not raw_keyword:
        return []
    return [
        keyword.strip()
        for keyword in re.split(r"[,，、;/\n\r]+", raw_keyword)
        if keyword.strip()
    ]


def append_unique_text(text_list: List[str], value: str) -> None:
    clean_value = re.sub(r"\s+", " ", value or "").strip()
    if clean_value and clean_value not in text_list:
        text_list.append(clean_value)


def build_guangdong_first_keyword_list(
    keywords: List[str],
    industry: str,
    include_raw_keyword: bool = True,
) -> List[str]:
    base_keyword_list = []
    for keyword_text in keywords:
        for keyword in split_public_search_keyword(keyword_text):
            append_unique_text(base_keyword_list, keyword)
    for keyword in INDUSTRY_PUBLIC_SEARCH_KEYWORD_MAP.get(industry, []):
        append_unique_text(base_keyword_list, keyword)

    result_list = []
    raw_tail_list = []
    for keyword in base_keyword_list:
        if is_guangdong_text(keyword):
            append_unique_text(result_list, keyword)
            continue
        for prefix in GUANGDONG_PRIORITY_PREFIX_LIST:
            append_unique_text(result_list, f"{prefix} {keyword}")
        if include_raw_keyword:
            append_unique_text(raw_tail_list, keyword)

    for keyword in raw_tail_list:
        append_unique_text(result_list, keyword)

    return result_list[:PUBLIC_WEB_SEARCH_KEYWORD_LIMIT]


@dataclass
class AlibabaCandidate:
    source_keyword: str
    company_name: str
    product_name: str
    shop_url: str
    profile_url: str
    raw_text: str
    search_url: str = ""
    card_index: int = -1


@dataclass
class MadeInChinaCandidate:
    source_keyword: str
    company_name: str
    product_name: str
    profile_url: str
    region_text: str
    raw_text: str
    search_url: str = ""
    card_index: int = -1


@dataclass
class BrowserSession:
    context: object
    browser: object = None


@dataclass
class DouyinCandidate:
    source_keyword: str
    nickname: str
    company_name: str
    product_name: str
    phone: str
    website_url: str
    shop_url: str
    profile_url: str
    sample_video_url: str
    raw_text: str
    is_blue_v: bool
    is_enterprise_verified: bool
    commercial_keyword_count: int


class DouyinPublicCollector:
    COMPANY_PATTERN = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,80}"
        r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|厂|商行|经营部|工作室))"
    )
    ENTERPRISE_TOKEN_LIST = ["企业认证", "蓝V", "蓝 V", "官方认证", "企业号", "营业执照"]
    BUSINESS_KEYWORD_LIST = ["工厂", "批发", "OEM", "ODM", "代工", "加工", "供应链", "源头", "跨境", "外贸"]
    BLOCKED_URL_TOKEN_LIST = ["login", "passport", "verify", "captcha"]
    BLOCKED_TEXT_TOKEN_LIST = [
        "请完成验证",
        "安全验证",
        "拖动滑块",
        "验证码",
        "访问过于频繁",
        "登录后继续",
        "账号安全",
    ]

    def __init__(self):
        self.config = get_config()

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        clean_keyword_list = [keyword.strip() for keyword in keywords if keyword.strip()]
        douyin_lead_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()

        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            page = context.new_page()
            try:
                for keyword in clean_keyword_list:
                    if len(douyin_lead_list) >= collect_limit:
                        break
                    self.goto_search_page(page, keyword)
                    candidate_list = self.extract_candidate_list(page, keyword, industry)
                    for candidate in candidate_list:
                        if len(douyin_lead_list) >= collect_limit:
                            break
                        lead = self.build_lead(candidate, industry)
                        if lead is None:
                            continue
                        dedupe_key = self.build_dedupe_key(lead)
                        if dedupe_key in dedupe_key_set:
                            continue
                        dedupe_key_set.add(dedupe_key)
                        douyin_lead_list.append(lead)
                    self.wait_between_page()
            finally:
                context.close()

        if not douyin_lead_list:
            return []

        qcc_lead_list = QichachaPublicWebCollector().collect_by_company_names(
            industry=industry,
            company_name_list=[lead.suspected_company_name for lead in douyin_lead_list],
            collect_limit=collect_limit,
        )
        return self.merge_qcc_public_leads(douyin_lead_list, qcc_lead_list)

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        context_args = {
            "headless": self.config.douyin_public_web_headless,
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        if self.config.douyin_public_web_browser_channel:
            context_args["channel"] = self.config.douyin_public_web_browser_channel
        try:
            return playwright.chromium.launch_persistent_context(
                str(self.config.douyin_public_web_user_data_dir),
                **context_args,
            )
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured Douyin browser channel is unavailable, fallback to bundled chromium")
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(
                str(self.config.douyin_public_web_user_data_dir),
                **context_args,
            )

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.config.douyin_public_web_user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"抖音采集专用浏览器资料目录正在被占用，请先关闭采集浏览器后再启动任务。当前占用进程：{process_text}")

    def goto_search_page(self, page, keyword: str) -> None:
        search_url_list = [
            f"https://www.douyin.com/search/{quote_plus(keyword)}?type=user",
            f"https://www.douyin.com/search/{quote_plus(keyword)}?type=video",
        ]
        last_error = None
        for search_url in search_url_list:
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=self.config.douyin_public_web_page_timeout_ms)
                page.wait_for_timeout(2600)
                self.assert_public_page_allowed(page)
                return
            except PlaywrightTimeoutError as ex:
                last_error = ex
                logger.warning("Douyin public search page timeout, url=%s", search_url)
            except PlaywrightError as ex:
                last_error = ex
                if not self.is_recoverable_navigation_error(ex):
                    raise
                logger.warning("Douyin public search navigation interrupted, url=%s, error=%s", search_url, self.clean_text(str(ex))[:160])
                page.wait_for_timeout(1600)
                self.assert_public_page_allowed(page)
        if last_error:
            raise RuntimeError(f"抖音公开搜索页打开失败：{self.clean_text(str(last_error))[:180]}")

    def assert_public_page_allowed(self, page) -> None:
        blocked_reason = self.get_blocked_reason(page)
        if not blocked_reason:
            return
        if self.config.douyin_public_web_manual_verify_enabled:
            self.wait_for_manual_recovery(page, blocked_reason)
            return
        raise RuntimeError(f"{blocked_reason}，已停止采集")

    def get_blocked_reason(self, page) -> str:
        page_url = page.url.lower()
        page_text = self.get_page_text(page)[:4000]
        if any(token in page_url for token in self.BLOCKED_URL_TOKEN_LIST):
            return "抖音公开页面跳转到登录/验证页"
        if any(token in page_text for token in self.BLOCKED_TEXT_TOKEN_LIST):
            return "抖音公开页面出现登录/验证/风控要求"
        return ""

    def wait_for_manual_recovery(self, page, blocked_reason: str) -> None:
        logger.warning("%s，等待人工完成验证或登录", blocked_reason)
        try:
            page.bring_to_front()
        except PlaywrightError:
            logger.warning("Could not bring Douyin page to front")

        start_time = time.monotonic()
        timeout_seconds = self.config.douyin_public_web_manual_verify_timeout_seconds
        poll_seconds = self.config.douyin_public_web_manual_verify_poll_seconds
        while time.monotonic() - start_time <= timeout_seconds:
            page.wait_for_timeout(int(poll_seconds * 1000))
            if not self.get_blocked_reason(page):
                page.wait_for_timeout(1200)
                logger.info("抖音页面已人工恢复，继续采集公开页面")
                return
        raise RuntimeError(f"{blocked_reason}，人工验证等待超时，已停止采集")

    def extract_candidate_list(self, page, keyword: str, industry: str) -> List[DouyinCandidate]:
        raw_item_list = page.evaluate(
            """
            () => {
              const isVisible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && rect.width > 0
                  && rect.height > 0;
              };
              return Array.from(document.querySelectorAll('a[href], div, section, li'))
                .filter(isVisible)
                .slice(0, 900)
                .map((element) => {
                  const card = element.closest(
                    'li, section, article, div[class*="card"], div[class*="item"], div[class*="result"], div[class*="user"], div[class*="video"]'
                  );
                  const parent = card || element;
                  const anchor = parent.querySelector && parent.querySelector('a[href]');
                  return {
                    href: (element.href || (anchor && anchor.href) || '').trim(),
                    text: (element.innerText || '').trim(),
                    parentText: ((parent && parent.innerText) || '').trim().slice(0, 1800),
                    title: (element.getAttribute && (element.getAttribute('title') || element.getAttribute('aria-label') || '')) || ''
                  };
                });
            }
            """
        )
        candidate_list = []
        for raw_item in raw_item_list:
            candidate = self.build_candidate(keyword, industry, raw_item)
            if candidate is not None:
                candidate_list.append(candidate)
        return self.dedupe_candidate_list(candidate_list)

    def build_candidate(self, keyword: str, industry: str, raw_item: Dict) -> Optional[DouyinCandidate]:
        raw_href = self.normalize_url(raw_item.get("href", ""))
        href = raw_href
        merged_text = self.clean_text(
            " ".join([raw_item.get("text", ""), raw_item.get("title", ""), raw_item.get("parentText", "")])
        )
        if not merged_text:
            return None
        company_name = self.extract_company_name(merged_text)
        commercial_keyword_count = self.count_business_keyword(merged_text)
        is_blue_v = self.is_blue_v_text(merged_text)
        is_enterprise_verified = self.is_enterprise_text(merged_text)
        if not company_name:
            return None
        if commercial_keyword_count == 0 and not is_blue_v and not is_enterprise_verified:
            return None
        phone = self.extract_phone(merged_text)
        profile_url = href if self.is_valid_douyin_url(href) else ""
        return DouyinCandidate(
            source_keyword=keyword,
            nickname=self.extract_nickname(merged_text, company_name),
            company_name=company_name,
            product_name=self.extract_product_name(merged_text, keyword, industry),
            phone=phone,
            website_url=self.extract_website_url(merged_text),
            shop_url=self.extract_shop_url(profile_url, merged_text),
            profile_url=profile_url,
            sample_video_url=profile_url if "/video/" in profile_url else "",
            raw_text=merged_text[:3000],
            is_blue_v=is_blue_v,
            is_enterprise_verified=is_enterprise_verified,
            commercial_keyword_count=commercial_keyword_count,
        )

    def build_lead(self, candidate: DouyinCandidate, industry: str) -> Optional[CollectedLeadDTO]:
        return CollectedLeadDTO(
            source_type=SOURCE_TYPE_DOUYIN_QCC,
            source_keyword=candidate.source_keyword,
            industry=industry,
            suspected_company_name=candidate.company_name,
            douyin_nickname=candidate.nickname,
            product_name=candidate.product_name,
            phone=candidate.phone,
            phone_source="抖音公开页可见字段" if candidate.phone else "",
            website_url=candidate.website_url,
            shop_url=candidate.shop_url,
            profile_url=candidate.profile_url,
            sample_video_url=candidate.sample_video_url,
            is_blue_v=candidate.is_blue_v,
            is_enterprise_verified=candidate.is_enterprise_verified,
            region_text=candidate.raw_text,
            commercial_keyword_count=candidate.commercial_keyword_count,
        )

    def merge_qcc_public_leads(
        self,
        douyin_lead_list: List[CollectedLeadDTO],
        qcc_lead_list: List[CollectedLeadDTO],
    ) -> List[CollectedLeadDTO]:
        result_list = []
        for douyin_lead in douyin_lead_list:
            qcc_lead = self.find_qcc_company_match(douyin_lead.suspected_company_name, qcc_lead_list)
            if qcc_lead is None:
                result_list.append(douyin_lead)
                continue
            phone_list = self.dedupe_text_list(
                self.split_phone_text(douyin_lead.phone) + self.split_phone_text(qcc_lead.phone)
            )
            if phone_list:
                douyin_lead.phone = "；".join(phone_list)
                douyin_lead.phone_source = "抖音公开页 + 企查查公开页可见字段"
            elif qcc_lead.phone_source:
                douyin_lead.phone = douyin_lead.phone or qcc_lead.phone
                douyin_lead.phone_source = qcc_lead.phone_source
            douyin_lead.contact_name = (
                douyin_lead.contact_name
                or qcc_lead.contact_name
                or qcc_lead.legal_person
                or douyin_lead.legal_person
            )
            douyin_lead.legal_person = qcc_lead.legal_person or douyin_lead.legal_person
            douyin_lead.company_status = qcc_lead.company_status or douyin_lead.company_status
            douyin_lead.business_scope = qcc_lead.business_scope or douyin_lead.business_scope
            douyin_lead.registered_address = qcc_lead.registered_address or douyin_lead.registered_address
            douyin_lead.risk_tag = qcc_lead.risk_tag or douyin_lead.risk_tag
            douyin_lead.region_text = " ".join(
                [douyin_lead.region_text, qcc_lead.region_text, qcc_lead.registered_address]
            )
            douyin_lead.product_name = douyin_lead.product_name or qcc_lead.product_name
            douyin_lead.commercial_keyword_count = max(
                douyin_lead.commercial_keyword_count,
                qcc_lead.commercial_keyword_count,
            )
            result_list.append(douyin_lead)
        return result_list

    def find_qcc_company_match(
        self,
        company_name: str,
        qcc_lead_list: List[CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        clean_company_name = self.clean_text(company_name)
        for lead in qcc_lead_list:
            if self.clean_text(lead.suspected_company_name) == clean_company_name:
                return lead
        for lead in qcc_lead_list:
            qcc_company_name = self.clean_text(lead.suspected_company_name)
            if clean_company_name in qcc_company_name or qcc_company_name in clean_company_name:
                return lead
        return None

    def extract_company_name(self, text: str) -> str:
        for match in self.COMPANY_PATTERN.finditer(text):
            company_name = match.group(1).strip()
            if self.is_valid_company_name(company_name):
                return company_name
        return ""

    def is_valid_company_name(self, company_name: str) -> bool:
        if len(company_name) < 4:
            return False
        return not any(token in company_name for token in ["抖音", "登录", "搜索", "验证码", "官方客服"])

    def extract_nickname(self, text: str, company_name: str) -> str:
        clean_text = self.clean_text(text.replace(company_name, " "))
        if not clean_text:
            return ""
        return re.split(r"\s|企业认证|蓝V|蓝 V|简介|主营", clean_text)[0][:40]

    def extract_product_name(self, text: str, keyword: str, industry: str) -> str:
        business_scope = self.extract_after_label(text, ["主营", "简介", "经营范围"], 100)
        if business_scope:
            return business_scope[:80]
        for business_keyword in self.BUSINESS_KEYWORD_LIST:
            if business_keyword in text:
                return f"{industry}{business_keyword}"
        return keyword[:80] if keyword else industry

    def extract_after_label(self, text: str, label_list: List[str], max_length: int) -> str:
        for label in label_list:
            index = text.find(label)
            if index < 0:
                continue
            value = text[index + len(label): index + len(label) + max_length]
            value = re.sub(r"^[：:\s]+", "", value)
            value = re.split(r"(?=联系电话|电话|官网|店铺|企业认证|蓝V|蓝 V)", value)[0]
            value = value.strip(" ：:，,；;。")
            if value:
                return value
        return ""

    def extract_phone(self, text: str) -> str:
        return clean_public_phone_text(text, include_service=False)

    def split_phone_text(self, phone_text: str) -> List[str]:
        return split_public_phone_text(phone_text, include_service=False)

    def extract_website_url(self, text: str) -> str:
        match = re.search(r"(https?://[A-Za-z0-9./?&_%#=\-]+|www\.[A-Za-z0-9./?&_%#=\-]+)", text)
        if not match:
            return ""
        url = match.group(1)
        return url if url.startswith("http") else f"https://{url}"

    def extract_shop_url(self, href: str, text: str) -> str:
        if href and ("店铺" in text or "橱窗" in text or "商品" in text):
            return href
        return ""

    def is_blue_v_text(self, text: str) -> bool:
        return "蓝V" in text or "蓝 V" in text

    def is_enterprise_text(self, text: str) -> bool:
        return any(token in text for token in self.ENTERPRISE_TOKEN_LIST)

    def count_business_keyword(self, text: str) -> int:
        return sum(1 for keyword in self.BUSINESS_KEYWORD_LIST if keyword in text)

    def normalize_url(self, url: str) -> str:
        clean_url = (url or "").strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        return clean_url

    def is_valid_douyin_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        parsed_url = urlparse(url)
        return parsed_url.netloc.lower().endswith("douyin.com")

    def get_page_text(self, page) -> str:
        try:
            return page.locator("body").inner_text(timeout=5000)
        except PlaywrightError:
            return ""

    def is_browser_channel_unavailable(self, ex: PlaywrightError) -> bool:
        message = str(ex).lower()
        return "executable doesn't exist" in message or "not found" in message

    def is_recoverable_navigation_error(self, ex: PlaywrightError) -> bool:
        message = str(ex)
        return "net::ERR_ABORTED" in message or "frame was detached" in message

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self.clean_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"抖音公开页采集浏览器启动失败：{message}"

    def clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def build_dedupe_key(self, lead: CollectedLeadDTO) -> str:
        return lead.suspected_company_name or lead.profile_url

    def dedupe_candidate_list(self, candidate_list: List[DouyinCandidate]) -> List[DouyinCandidate]:
        result_list = []
        dedupe_key_set = set()
        for candidate in candidate_list:
            dedupe_key = candidate.company_name or candidate.profile_url
            if not dedupe_key or dedupe_key in dedupe_key_set:
                continue
            dedupe_key_set.add(dedupe_key)
            result_list.append(candidate)
        return result_list

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result_list = []
        dedupe_set = set()
        for text in text_list:
            clean_text = text.strip()
            if not clean_text or clean_text in dedupe_set:
                continue
            dedupe_set.add(clean_text)
            result_list.append(clean_text)
        return result_list

    def wait_between_page(self) -> None:
        time.sleep(self.config.douyin_public_web_request_interval_seconds)


class Alibaba1688PublicPageCollector:
    def __init__(self):
        self.config = get_config()
        self.existing_dedupe_key_set = set()
        self.last_search_keyword_list: List[str] = []
        self.last_raw_item_count = 0
        self.last_candidate_count = 0
        self.last_candidate_reject_reason_count: Dict[str, int] = {}
        self.last_detail_checked_count = 0
        self.last_detail_passed_count = 0
        self.last_detail_reject_reason_count: Dict[str, int] = {}
        self.last_search_page_count = 0
        self.last_search_candidate_next_page_number = 1
        self.last_search_pagination_reached_end = False
        self.last_search_page_signature_map: Dict[str, Tuple[str, ...]] = {}
        self.repeated_search_page_count_map: Dict[str, int] = {}
        self.last_repeated_search_page_guard_count = 0
        self.last_existing_skip_count = 0
        self.last_run_dedupe_skip_count = 0
        self.last_public_lead_reject_reason_count: Dict[str, int] = {}
        self.last_collect_diagnostic = ""
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        try:
            self.task_event_callback(event_type, level, message)
        except Exception:
            logger.warning("1688 task event callback failed")

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.existing_dedupe_key_set = set()
        for identity in identity_list:
            for field_name in ("company_name", "suspected_company_name", "shop_url", "profile_url"):
                dedupe_key = self.normalize_dedupe_text(identity.get(field_name, ""))
                if dedupe_key:
                    self.existing_dedupe_key_set.add(dedupe_key)

    def is_existing_lead(self, lead: CollectedLeadDTO) -> bool:
        if not self.existing_dedupe_key_set:
            return False
        for value in (lead.suspected_company_name, lead.shop_url, lead.profile_url):
            dedupe_key = self.normalize_dedupe_text(value)
            if dedupe_key and dedupe_key in self.existing_dedupe_key_set:
                return True
        return False

    def remember_collected_lead_identity(self, lead: CollectedLeadDTO) -> None:
        for value in (lead.suspected_company_name, lead.shop_url, lead.profile_url):
            dedupe_key = self.normalize_dedupe_text(value)
            if dedupe_key:
                self.existing_dedupe_key_set.add(dedupe_key)

    def get_search_progress_file_path(self) -> Path:
        return self.config.database_path.parent / "1688_search_progress.json"

    def build_search_progress_key(self, target_city: str, keyword: str) -> str:
        return self.normalize_dedupe_text(f"{target_city}|{keyword}")

    def load_search_progress_map(self) -> Dict[str, int]:
        progress_file_path = self.get_search_progress_file_path()
        if not progress_file_path.exists():
            return {}
        try:
            data = json.loads(progress_file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: Dict[str, int] = {}
        for key, value in data.items():
            try:
                result[str(key)] = max(1, int(value))
            except (TypeError, ValueError):
                continue
        return result

    def save_search_progress_map(self, progress_map: Dict[str, int]) -> None:
        progress_file_path = self.get_search_progress_file_path()
        progress_file_path.parent.mkdir(parents=True, exist_ok=True)
        progress_file_path.write_text(
            json.dumps(progress_map, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_search_resume_page(self, target_city: str, keyword: str) -> int:
        progress_key = self.build_search_progress_key(target_city, keyword)
        if not progress_key:
            return 1
        return self.load_search_progress_map().get(progress_key, 1)

    def save_search_resume_page(self, target_city: str, keyword: str, next_page_number: int) -> None:
        progress_key = self.build_search_progress_key(target_city, keyword)
        if not progress_key:
            return
        progress_map = self.load_search_progress_map()
        progress_map[progress_key] = max(1, int(next_page_number or 1))
        self.save_search_progress_map(progress_map)

    def build_search_candidate_limit(self, remaining_count: int) -> int:
        if remaining_count <= 0:
            return 0
        if remaining_count <= 12:
            return remaining_count
        buffer_count = min(18, max(4, (remaining_count + 3) // 4))
        return remaining_count + buffer_count

    def build_balanced_search_candidate_limit(self, remaining_count: int, uncovered_keyword_count: int) -> int:
        if remaining_count <= 0:
            return 0
        if uncovered_keyword_count <= 1:
            return self.build_search_candidate_limit(remaining_count)
        fair_count = max(1, (remaining_count + uncovered_keyword_count - 1) // uncovered_keyword_count)
        return self.build_search_candidate_limit(min(remaining_count, fair_count))

    def wait_after_collected_lead(self, collected_count: int, collect_limit: int) -> None:
        batch_size = min(max(self.config.collector_batch_size, 1), 5)
        if collect_limit <= 12:
            batch_size = collect_limit
        cooldown_seconds = max(
            self.config.collector_batch_cooldown_seconds,
            self.config.alibaba_1688_request_interval_seconds * 2.5,
        )
        if should_wait_for_batch_cooldown(
            collected_count,
            collect_limit,
            batch_size,
            cooldown_seconds,
        ):
            wait_text = format_wait_seconds(cooldown_seconds)
            self.emit_task_event(
                "collecting",
                "info",
                f"1688已采集 {collected_count} 条，暂停 {wait_text} 秒后继续下一批。",
            )
            sleep_with_jitter(cooldown_seconds, 0.25, cooldown_seconds)
            return

    def collect(
        self,
        industry: str,
        keywords: List[str],
        collect_limit: int,
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
    ) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        self.reset_collect_diagnostic()
        clean_target_city = self.normalize_target_city(target_city)
        clean_keyword_list = self.build_search_keyword_list(
            industry,
            keywords,
            target_city=clean_target_city,
            collect_limit=collect_limit,
        )
        self.last_search_keyword_list = clean_keyword_list
        if collect_limit <= 0:
            raise RuntimeError("1688采集数量必须大于 0，请重新设置采集数量。")
        if not clean_keyword_list:
            raise RuntimeError(
                f"1688采集关键词无效：当前行业为“{industry}”，请填写要采集的产品关键词，例如“蓝牙耳机、数据线、美甲、女装批发”。"
            )

        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        detail_fallback_count = 0

        with sync_playwright() as playwright:
            browser_session = self.create_browser_session(playwright)
            context = browser_session.context
            page = context.new_page()
            try:
                for keyword in clean_keyword_list:
                    if len(result_list) >= collect_limit:
                        break
                    visited_resume_page_set = set()
                    while len(result_list) < collect_limit:
                        remaining_count = collect_limit - len(result_list)
                        candidate_search_limit = self.build_search_candidate_limit(remaining_count)
                        resume_page_number = self.load_search_resume_page(clean_target_city, keyword)
                        if resume_page_number in visited_resume_page_set:
                            break
                        visited_resume_page_set.add(resume_page_number)
                        candidate_list = self.search_candidate(
                            page,
                            keyword,
                            candidate_search_limit,
                            industry,
                            target_city=clean_target_city,
                            start_page_number=resume_page_number,
                        )
                        next_page_number = self.last_search_candidate_next_page_number
                        self.save_search_resume_page(
                            clean_target_city,
                            keyword,
                            next_page_number,
                        )
                        self.last_candidate_count = max(self.last_candidate_count, len(candidate_list))
                        for candidate in candidate_list:
                            if len(result_list) >= collect_limit:
                                break
                            detail_fallback_index = detail_fallback_count
                            is_detail_fallback = self.should_use_detail_fallback(candidate, detail_fallback_index)
                            if is_detail_fallback:
                                self.last_detail_checked_count += 1
                                detail_fallback_count += 1
                                self.wait_before_detail_visit()
                            lead = self.collect_search_candidate_to_lead(page, candidate, industry, detail_fallback_index)
                            if lead is None:
                                self.record_public_lead_reject("搜索页候选无法生成线索")
                                continue
                            if is_detail_fallback:
                                self.last_detail_passed_count += 1
                            if not has_public_phone_text(lead.phone):
                                lead.phone = "未公开"
                                if not lead.phone_source:
                                    lead.phone_source = "1688搜索页未展示公开电话"
                            if is_disqualified_public_lead(lead):
                                self.record_public_lead_reject(get_disqualified_lead_reason(lead) or "公开线索被过滤")
                                continue
                            dedupe_key = self.build_dedupe_key(lead)
                            if dedupe_key in dedupe_key_set:
                                self.last_run_dedupe_skip_count += 1
                                continue
                            if self.is_existing_lead(lead):
                                self.last_existing_skip_count += 1
                                continue
                            dedupe_key_set.add(dedupe_key)
                            result_list.append(lead)
                            self.remember_collected_lead_identity(lead)
                            self.wait_after_collected_lead(len(result_list), collect_limit)
                        if len(result_list) >= collect_limit:
                            break
                        if not candidate_list:
                            break
                        if next_page_number <= 1 or next_page_number in visited_resume_page_set:
                            break
                        self.wait_between_page()
            finally:
                self.close_browser_session(browser_session)
        if not result_list:
            self.last_collect_diagnostic = self.build_empty_collect_diagnostic()
        elif len(result_list) < collect_limit:
            self.last_collect_diagnostic = self.build_partial_collect_diagnostic(len(result_list), collect_limit)
        return result_list

    def should_use_detail_fallback(self, candidate: AlibabaCandidate, detail_fallback_count: int) -> bool:
        if not self.config.alibaba_1688_detail_fallback_enabled:
            return False
        if candidate.product_name:
            return False
        return detail_fallback_count < max(0, self.config.alibaba_1688_detail_fallback_limit)

    def collect_search_candidate_to_lead(
        self,
        page,
        candidate: AlibabaCandidate,
        industry: str,
        detail_fallback_count: int,
    ) -> Optional[CollectedLeadDTO]:
        if self.should_use_detail_fallback(candidate, detail_fallback_count):
            return self.enrich_candidate(page, candidate, industry)
        return self.build_fallback_lead_from_search_candidate(candidate, industry)

    def reset_collect_diagnostic(self) -> None:
        self.last_search_keyword_list = []
        self.last_raw_item_count = 0
        self.last_candidate_count = 0
        self.last_candidate_reject_reason_count = {}
        self.last_detail_checked_count = 0
        self.last_detail_passed_count = 0
        self.last_detail_reject_reason_count = {}
        self.last_search_page_count = 0
        self.last_search_candidate_next_page_number = 1
        self.last_search_pagination_reached_end = False
        self.last_search_page_signature_map = {}
        self.repeated_search_page_count_map = {}
        self.last_repeated_search_page_guard_count = 0
        self.last_existing_skip_count = 0
        self.last_run_dedupe_skip_count = 0
        self.last_public_lead_reject_reason_count = {}
        self.last_collect_diagnostic = ""

    def build_empty_collect_diagnostic(self) -> str:
        keyword_text = "、".join(self.last_search_keyword_list) if self.last_search_keyword_list else "无有效关键词"
        page_text = f"实际翻页 {self.last_search_page_count} 页，"
        if self.last_candidate_count > 0:
            reason_text = self.format_no_saved_lead_reason()
            if self.last_detail_checked_count == 0:
                return (
                    f"1688本次未采集到公开线索：候选企业 {self.last_candidate_count} 个，{reason_text}"
                    f"{page_text}实际搜索词：{keyword_text}。"
                )
            return (
                f"1688本次未采集到公开线索：候选企业 {self.last_candidate_count} 个，已检查详情页 "
                f"{self.last_detail_checked_count} 个，通过行业/广东/企业名校验 {self.last_detail_passed_count} 个。"
                f"{self.format_detail_reject_reason()}{reason_text}{page_text}实际搜索词：{keyword_text}。"
            )
        if self.last_raw_item_count == 0:
            return (
                f"1688本次未采集到公开线索：{page_text}实际搜索词为「{keyword_text}」，搜索页没有解析到企业卡片。"
                "请确认弹出的 1688 浏览器停留在广东找工厂搜索结果页，且没有登录/验证/访问限制遮挡。"
            )
        if self.last_candidate_count == 0:
            return (
                f"1688本次未采集到公开线索：搜索页解析到 {self.last_raw_item_count} 个可见块，"
                f"但没有通过候选卡片过滤。{self.format_candidate_reject_reason()}{page_text}实际搜索词：{keyword_text}。"
            )
        return f"1688本次未采集到公开线索：{page_text}实际搜索词：{keyword_text}。"

    def build_partial_collect_diagnostic(self, collected_count: int, collect_limit: int) -> str:
        keyword_text = "、".join(self.last_search_keyword_list) if self.last_search_keyword_list else "无有效关键词"
        reason_list = []
        if self.last_existing_skip_count:
            reason_list.append(f"已存在/重复线索 {self.last_existing_skip_count} 条")
        if self.last_run_dedupe_skip_count:
            reason_list.append(f"本批重复候选 {self.last_run_dedupe_skip_count} 条")
        if self.last_repeated_search_page_guard_count:
            reason_list.append("1688返回重复结果页，已自动停止无效翻页")
        if self.last_public_lead_reject_reason_count:
            reason_list.append(self.format_public_lead_reject_reason().rstrip("。"))
        if self.last_candidate_reject_reason_count:
            reason_list.append(self.format_candidate_reject_reason().rstrip("。"))
        reason_text = "；".join(reason_list) if reason_list else "候选页数已扫描完或页面可见结果不足"
        return (
            f"1688本次只采集到 {collected_count}/{collect_limit} 条公开线索；"
            f"{reason_text}；实际翻页 {self.last_search_page_count} 页；实际搜索词：{keyword_text}。"
        )

    def create_browser_session(self, playwright) -> BrowserSession:
        if self.config.alibaba_1688_manual_verify_enabled:
            context = self.launch_persistent_context(playwright)
            return BrowserSession(context=context)
        browser = self.launch_browser(playwright)
        context = browser.new_context(locale="zh-CN", viewport={"width": 1366, "height": 900})
        return BrowserSession(context=context, browser=browser)

    def close_browser_session(self, browser_session: BrowserSession) -> None:
        try:
            browser_session.context.close()
        except PlaywrightError as ex:
            logger.info("1688 browser context already closed during cleanup, error=%s", self.clean_text(str(ex))[:160])
        if browser_session.browser is None:
            return
        try:
            browser_session.browser.close()
        except PlaywrightError as ex:
            logger.info("1688 browser already closed during cleanup, error=%s", self.clean_text(str(ex))[:160])

    def build_launch_args(self) -> Dict:
        launch_args = {"headless": self.config.alibaba_1688_headless}
        if self.config.alibaba_1688_browser_channel:
            launch_args["channel"] = self.config.alibaba_1688_browser_channel
        return launch_args

    def launch_browser(self, playwright):
        launch_args = self.build_launch_args()
        try:
            return playwright.chromium.launch(**launch_args)
        except PlaywrightError as ex:
            if "channel" not in launch_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured browser channel is unavailable, fallback to bundled chromium")
            launch_args.pop("channel")
            return playwright.chromium.launch(**launch_args)

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        launch_args = self.build_launch_args()
        context_args = {
            **launch_args,
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        try:
            return playwright.chromium.launch_persistent_context(
                str(self.config.alibaba_1688_user_data_dir),
                **context_args,
            )
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured browser channel is unavailable, fallback to bundled chromium")
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(
                str(self.config.alibaba_1688_user_data_dir),
                **context_args,
            )

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.config.alibaba_1688_user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"{PROFILE_BUSY_MESSAGE}。当前占用进程：{process_text}")

    def is_browser_channel_unavailable(self, ex: PlaywrightError) -> bool:
        message = str(ex).lower()
        return "executable doesn't exist" in message or "not found" in message

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self.clean_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"1688采集浏览器启动失败：{message}"

    def open_search_result_page(self, page, keyword: str, page_number: int) -> bool:
        current_page_number = self.get_current_search_page_number(page)
        if (
            page_number > 1
            and current_page_number > 0
            and self.is_current_search_result_session(page, keyword)
        ):
            logger.info(
                "1688 reuse current search session, keyword=%s, current_page=%s, target_page=%s",
                keyword,
                current_page_number,
                page_number,
            )
            return self.go_to_search_page(page, page_number)
        search_url_list = self.build_search_url_list(keyword, 1)
        if not search_url_list:
            return False
        search_url = search_url_list[0]
        logger.info("1688 initial search start, keyword=%s, url=%s", keyword, search_url)
        self.goto_public_page(page, search_url)
        if not self.wait_for_search_result_ready(page):
            return False
        if page_number <= 1:
            return True
        self.scroll_result_page_to_load(page)
        return self.go_to_search_page(page, page_number)

    def wait_for_search_result_ready(self, page) -> bool:
        try:
            page.wait_for_function(
                r"""
                () => {
                  const currentPage = document.querySelector('.space-common-pagination .fui-current');
                  if (currentPage) {
                    return true;
                  }
                  const bodyText = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
                  const companyPattern = /[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,80}?(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|商行|经营部|工作室|工厂|厂)/;
                  const resultTokenList = ['响应率', '履约率', '回头率', '超级工厂', '实力工厂', '来样加工', '来图加工'];
                  if (companyPattern.test(bodyText) && resultTokenList.some((token) => bodyText.includes(token))) {
                    return true;
                  }
                  return ['没有找到相关', '暂无相关', '未找到相关'].some((token) => bodyText.includes(token));
                }
                """,
                timeout=self.config.alibaba_1688_page_timeout_ms,
            )
            return True
        except PlaywrightTimeoutError:
            logger.warning(
                "1688 search result readiness timeout, actual_url=%s",
                self.clean_text(str(getattr(page, "url", "")))[:300],
            )
            self.assert_public_page_allowed(page)
            return False

    def is_current_search_result_session(self, page, keyword: str) -> bool:
        current_url = self.clean_text(str(getattr(page, "url", "")))
        if "/company/pc/factory_search.htm" not in current_url:
            return False
        expected_keyword = self.encode_1688_query_value(self.clean_text(keyword)).upper()
        query_text = urlparse(current_url).query
        query_value_map = {}
        for query_item in query_text.split("&"):
            key, separator, value = query_item.partition("=")
            if separator:
                query_value_map[key.lower()] = value.upper()
        return (
            query_value_map.get("keywords") == expected_keyword
            and self.is_guangdong_filtered_search_url(current_url)
        )

    def get_current_search_page_number(self, page) -> int:
        try:
            current_page = page.locator(".space-common-pagination .fui-current").first
            if current_page.count() <= 0:
                return 0
            text = self.clean_text(current_page.inner_text())
            return int(text) if text.isdigit() else 0
        except (PlaywrightError, TypeError, ValueError):
            return 0

    @staticmethod
    def can_advance_to_search_page(
        current_page_number: int,
        target_page_number: int,
        visible_page_number_list: List[int],
    ) -> bool:
        if target_page_number != current_page_number + 1:
            return True
        return any(page_number >= target_page_number for page_number in visible_page_number_list)

    def go_to_search_page(self, page, page_number: int) -> bool:
        target_page_number = max(1, int(page_number or 1))
        current_page_number = self.get_current_search_page_number(page)
        if current_page_number == target_page_number:
            return True
        try:
            pagination = page.locator(".space-common-pagination").first
            pagination.wait_for(state="visible", timeout=self.config.alibaba_1688_page_timeout_ms)
            pagination.scroll_into_view_if_needed()
            wait_for_page_timeout_with_jitter(page, 450, 0.25, 300)

            clicked = False
            visible_page_number_list = []
            page_item_list = pagination.locator(".fui-page-item")
            for index in range(page_item_list.count()):
                page_item = page_item_list.nth(index)
                page_item_text = self.clean_text(page_item.inner_text())
                if page_item_text.isdigit():
                    visible_page_number_list.append(int(page_item_text))
                if page_item_text != str(target_page_number):
                    continue
                page_item.click()
                clicked = True
                break

            if not clicked and current_page_number > 0 and target_page_number == current_page_number + 1:
                if not self.can_advance_to_search_page(
                    current_page_number,
                    target_page_number,
                    visible_page_number_list,
                ):
                    logger.info(
                        "1688 native pagination reached last page, current_page=%s, visible_pages=%s",
                        current_page_number,
                        visible_page_number_list,
                    )
                    self.last_search_pagination_reached_end = True
                    return False
                next_button = pagination.locator(".fui-next").first
                next_class = self.clean_text(next_button.get_attribute("class") or "")
                if next_button.count() > 0 and "disabled" not in next_class:
                    next_button.click()
                    clicked = True

            if not clicked:
                page_input = pagination.locator(".input-page").first
                confirm_button = pagination.locator(".paging-to-page-button").first
                if page_input.count() <= 0 or confirm_button.count() <= 0:
                    return False
                page_input.fill(str(target_page_number))
                confirm_button.click()

            page.wait_for_function(
                """
                (expectedPage) => {
                  const current = document.querySelector('.space-common-pagination .fui-current');
                  return current && (current.textContent || '').trim() === String(expectedPage);
                }
                """,
                arg=target_page_number,
                timeout=self.config.alibaba_1688_page_timeout_ms,
            )
            wait_for_page_timeout_with_jitter(page, 1000, 0.35, 650)
            self.assert_public_page_allowed(page)
            logger.info(
                "1688 native pagination confirmed, target_page=%s, actual_url=%s",
                target_page_number,
                self.clean_text(str(getattr(page, "url", "")))[:300],
            )
            return True
        except PlaywrightTimeoutError:
            logger.warning(
                "1688 native pagination timeout, target_page=%s, current_page=%s, actual_url=%s",
                target_page_number,
                self.get_current_search_page_number(page),
                self.clean_text(str(getattr(page, "url", "")))[:300],
            )
            self.assert_public_page_allowed(page)
            return False
        except PlaywrightError as ex:
            logger.warning(
                "1688 native pagination failed, target_page=%s, error=%s",
                target_page_number,
                self.clean_text(str(ex))[:180],
            )
            self.assert_public_page_allowed(page)
            return False

    def search_candidate(
        self,
        page,
        keyword: str,
        collect_limit: int,
        industry: str,
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
        start_page_number: int = 1,
    ) -> List[AlibabaCandidate]:
        if collect_limit <= 0 or not self.is_valid_search_keyword(industry, keyword):
            return []
        candidate_list: List[AlibabaCandidate] = []
        page_number = max(1, int(start_page_number or 1))
        max_page_count = self.build_search_max_page_count(collect_limit)
        if page_number > max_page_count:
            page_number = 1
        self.last_search_candidate_next_page_number = page_number
        empty_candidate_page_count = 0
        last_visited_page_number = page_number - 1
        repeated_result_guard_triggered = False
        pagination_failed = False
        self.last_search_pagination_reached_end = False
        if not self.open_search_result_page(page, keyword, page_number):
            if page_number <= 1:
                return []
            logger.warning(
                "1688 saved resume page is unavailable, fallback to first page, keyword=%s, resume_page=%s",
                keyword,
                page_number,
            )
            self.emit_task_event(
                "collecting",
                "warning",
                f"1688“{keyword}”原续采页第 {page_number} 页已失效，已自动回到第 1 页继续采集。",
            )
            page_number = 1
            self.last_search_candidate_next_page_number = 1
            self.last_search_pagination_reached_end = False
            if not self.open_search_result_page(page, keyword, page_number):
                return []
        while page_number <= max_page_count and len(candidate_list) < collect_limit:
            page_start_count = len(candidate_list)
            self.scroll_result_page_to_load(page)
            confirmed_page_number = self.get_current_search_page_number(page)
            if confirmed_page_number and confirmed_page_number != page_number:
                logger.warning(
                    "1688 page number mismatch, expected=%s, actual=%s, url=%s",
                    page_number,
                    confirmed_page_number,
                    self.clean_text(str(getattr(page, "url", "")))[:300],
                )
                pagination_failed = True
                break
            last_visited_page_number = page_number
            search_url = self.clean_text(str(getattr(page, "url", ""))) or self.build_search_url_list(keyword, 1)[0]
            logger.info("1688 search page parse, keyword=%s, page=%s, url=%s", keyword, page_number, search_url)
            raw_item_list = self.extract_raw_item_list(page)
            self.last_raw_item_count += len(raw_item_list)
            page_candidate_list: List[AlibabaCandidate] = []
            for raw_item in raw_item_list:
                candidate = self.build_candidate(keyword, raw_item, industry, target_city=target_city)
                if candidate is not None:
                    candidate.search_url = search_url
                    page_candidate_list.append(candidate)
                    candidate_list.append(candidate)
                    if len(candidate_list) >= collect_limit:
                        break
            candidate_list = self.dedupe_candidate_list(candidate_list)
            self.last_candidate_count = max(self.last_candidate_count, len(candidate_list))
            if self.should_stop_repeated_search_page(keyword, page_candidate_list):
                repeated_result_guard_triggered = True
                self.last_repeated_search_page_guard_count += 1
                logger.warning(
                    "1688 repeated result page detected, keyword=%s, page=%s, actual_url=%s",
                    keyword,
                    page_number,
                    self.clean_text(str(getattr(page, "url", "")))[:300],
                )
                self.emit_task_event(
                    "collecting",
                    "warning",
                    f"1688检测到“{keyword}”连续返回同一批企业，已停止当前搜索词的无效翻页。",
                )
            self.last_search_page_count += 1
            if repeated_result_guard_triggered:
                break
            if len(candidate_list) == page_start_count and page_number >= 2:
                empty_candidate_page_count += 1
                if empty_candidate_page_count >= ALIBABA_1688_EMPTY_CANDIDATE_PAGE_STOP_COUNT:
                    break
            else:
                empty_candidate_page_count = 0
            if len(candidate_list) >= collect_limit:
                break
            next_page_number = page_number + 1
            if next_page_number > max_page_count:
                break
            self.wait_between_page()
            if not self.go_to_search_page(page, next_page_number):
                if self.last_search_pagination_reached_end:
                    self.emit_task_event(
                        "collecting",
                        "info",
                        f"1688“{keyword}”已采集到搜索结果末页（第 {page_number} 页）。",
                    )
                else:
                    pagination_failed = True
                    self.emit_task_event(
                        "collecting",
                        "warning",
                        f"1688未能确认从第 {page_number} 页切换到第 {next_page_number} 页，已停止当前搜索词，避免重复采集第一页。",
                    )
                break
            page_number = next_page_number
        next_page_number = 1 if repeated_result_guard_triggered or self.last_search_pagination_reached_end else (
            last_visited_page_number + 1 if last_visited_page_number >= 1 else 1
        )
        if pagination_failed and last_visited_page_number >= 1:
            next_page_number = last_visited_page_number + 1
        if next_page_number > max_page_count:
            next_page_number = 1
        self.last_search_candidate_next_page_number = next_page_number
        return self.dedupe_candidate_list(candidate_list)

    def should_stop_repeated_search_page(
        self,
        keyword: str,
        page_candidate_list: List[AlibabaCandidate],
    ) -> bool:
        signature = tuple(
            sorted(
                {
                    self.normalize_dedupe_text(candidate.company_name)
                    for candidate in page_candidate_list
                    if self.normalize_dedupe_text(candidate.company_name)
                }
            )
        )
        if not signature:
            return False
        state_key = self.normalize_dedupe_text(keyword)
        previous_signature = self.last_search_page_signature_map.get(state_key, ())
        self.last_search_page_signature_map[state_key] = signature
        if not previous_signature:
            self.repeated_search_page_count_map[state_key] = 0
            return False
        previous_set = set(previous_signature)
        current_set = set(signature)
        overlap_ratio = len(previous_set & current_set) / max(len(previous_set), len(current_set))
        if overlap_ratio < ALIBABA_1688_REPEATED_PAGE_OVERLAP_RATIO:
            self.repeated_search_page_count_map[state_key] = 0
            return False
        repeated_count = self.repeated_search_page_count_map.get(state_key, 0) + 1
        self.repeated_search_page_count_map[state_key] = repeated_count
        return repeated_count >= ALIBABA_1688_REPEATED_PAGE_STOP_COUNT

    def build_search_max_page_count(self, collect_limit: int) -> int:
        if collect_limit <= 0:
            return 0
        return ALIBABA_1688_MAX_SEARCH_PAGE_COUNT

    def build_search_url_list(self, keyword: str, page_number: int) -> List[str]:
        clean_keyword = self.clean_text(keyword)
        if not clean_keyword:
            return []
        encoded_keyword = self.encode_1688_query_value(clean_keyword)
        encoded_province = self.encode_1688_query_value("广东")
        return [
            "https://s.1688.com/company/pc/factory_search.htm"
            f"?keywords={encoded_keyword}&province={encoded_province}&beginPage={page_number}",
        ]

    def is_guangdong_filtered_search_url(self, url: str) -> bool:
        clean_url = str(url or "")
        if not clean_url:
            return False
        return f"province={self.encode_1688_query_value('广东')}" in clean_url or "province=广东" in clean_url

    @staticmethod
    def encode_1688_query_value(value: str) -> str:
        # The 1688 factory-search route decodes query values as GBK on the public site.
        # GBK percent encoding keeps Chinese keywords readable in the search box.
        return quote_from_bytes(value.encode("gbk", errors="ignore"))

    def build_search_keyword_list(
        self,
        industry: str,
        keywords: List[str],
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
        collect_limit: Optional[int] = None,
    ) -> List[str]:
        keyword_list = []
        raw_keyword_list = []
        for keyword in keywords:
            raw_keyword_list.extend(re.split(r"[,，、;/\n\r]+", keyword or ""))
        if not raw_keyword_list:
            return []
        for raw_keyword in raw_keyword_list:
            keyword = self.clean_1688_search_keyword(raw_keyword)
            if not self.is_valid_search_keyword(industry, keyword):
                continue
            for expanded_keyword in self.build_city_priority_search_keyword_list(
                keyword,
                target_city=target_city,
                collect_limit=collect_limit,
            ):
                keyword_list.append(expanded_keyword)
        return self.dedupe_text_list(keyword_list)

    def interleave_keyword_variant_group_list(self, keyword_variant_group_list: List[List[str]]) -> List[str]:
        result_list = []
        max_variant_count = max((len(group) for group in keyword_variant_group_list), default=0)
        for variant_index in range(max_variant_count):
            for variant_group in keyword_variant_group_list:
                if variant_index < len(variant_group):
                    append_unique_text(result_list, variant_group[variant_index])
        return result_list

    def build_city_priority_search_keyword_list(
        self,
        keyword: str,
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
        collect_limit: Optional[int] = None,
    ) -> List[str]:
        clean_keyword = self.clean_1688_search_keyword(keyword)
        if not clean_keyword:
            return []
        if self.is_specific_company_search_keyword(clean_keyword):
            return [clean_keyword]
        normalized_keyword = self.remove_leading_guangdong_region_token(clean_keyword)
        result_list = []
        for city_name in self.normalize_target_city_list(target_city):
            if city_name == DEFAULT_GUANGDONG_TARGET_CITY:
                append_unique_text(result_list, f"广东{normalized_keyword}")
                append_unique_text(result_list, normalized_keyword)
                for guangdong_city_name in self.build_guangdong_province_search_city_list(collect_limit):
                    append_unique_text(result_list, f"{guangdong_city_name}{normalized_keyword}")
            elif normalized_keyword.startswith(city_name):
                append_unique_text(result_list, normalized_keyword)
            else:
                append_unique_text(result_list, f"{city_name}{normalized_keyword}")
        return result_list

    def build_guangdong_province_search_city_list(self, collect_limit: Optional[int] = None) -> List[str]:
        city_list = self.dedupe_text_list(PRIORITY_GUANGDONG_CITY_LIST + GUANGDONG_CITY_LIST)
        if collect_limit is None:
            return city_list
        clean_limit = max(1, int(collect_limit or 1))
        if clean_limit <= 10:
            return city_list[:4]
        if clean_limit <= 30:
            return city_list[:6]
        if clean_limit <= 50:
            return city_list[:10]
        return city_list

    def build_guangdong_product_search_keyword_list(
        self,
        keyword: str,
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
    ) -> List[str]:
        return self.build_city_priority_search_keyword_list(keyword, target_city=target_city)

    def normalize_target_city(self, target_city: str) -> str:
        city_list = self.normalize_target_city_list(target_city)
        if city_list == [DEFAULT_GUANGDONG_TARGET_CITY]:
            return DEFAULT_GUANGDONG_TARGET_CITY
        return ",".join(city_list)

    def normalize_target_city_list(self, target_city: str) -> List[str]:
        clean_target_city_text = self.clean_text(target_city)
        if clean_target_city_text in ("", "广东", DEFAULT_GUANGDONG_TARGET_CITY):
            return [DEFAULT_GUANGDONG_TARGET_CITY]
        city_list: List[str] = []
        for raw_city in re.split(r"[,，、;/\n\r]+", clean_target_city_text):
            clean_city = self.clean_text(raw_city)
            if clean_city in ("", "广东", DEFAULT_GUANGDONG_TARGET_CITY):
                continue
            city_name = normalize_city_name(clean_city)
            if city_name in GUANGDONG_CITY_LIST:
                append_unique_text(city_list, city_name)
        return city_list or [DEFAULT_GUANGDONG_TARGET_CITY]

    def remove_leading_guangdong_region_token(self, keyword: str) -> str:
        clean_keyword = self.clean_1688_search_keyword(keyword)
        region_token_list = ["广东省", "广东"]
        region_token_list.extend(f"{city_name}市" for city_name in GUANGDONG_CITY_LIST)
        region_token_list.extend(GUANGDONG_CITY_LIST)
        for token in region_token_list:
            if clean_keyword.startswith(token) and len(clean_keyword) > len(token) + 1:
                return clean_keyword[len(token) :]
        return clean_keyword

    @staticmethod
    def has_priority_city_token(keyword: str) -> bool:
        return any(city_name in (keyword or "") for city_name in GUANGDONG_CITY_LIST)

    def is_specific_company_search_keyword(self, keyword: str) -> bool:
        clean_keyword = self.clean_1688_search_keyword(keyword)
        if clean_keyword.endswith(("工厂", "厂家", "厂")) and not any(
            region_token in clean_keyword
            for region_token in ("区", "县", "镇", "街道")
        ):
            return False
        return bool(COMPANY_NAME_PATTERN.search(clean_keyword) and is_valid_enterprise_name(clean_keyword, []))

    def clean_1688_search_keyword(self, keyword: str) -> str:
        clean_keyword = self.clean_text(keyword)
        clean_keyword = re.sub(r"[\"'`“”‘’\[\]{}()（）<>《》]+", "", clean_keyword)
        clean_keyword = re.sub(r"\s+", "", clean_keyword)
        return clean_keyword.strip("，,。.;；、/|\\-_")

    @staticmethod
    def is_company_name_keyword(keyword: str) -> bool:
        return bool(COMPANY_NAME_PATTERN.search(keyword or ""))

    def is_valid_search_keyword(self, industry: str, keyword: str) -> bool:
        if len(keyword) < 2:
            return False
        if len(keyword) > 40 or self.contains_mojibake(keyword):
            return False
        if keyword.isdigit():
            return False
        if not re.search(r"[\u4e00-\u9fa5A-Za-z]", keyword):
            return False
        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [])
        if not industry_token_list:
            return True
        upper_keyword = keyword.upper()
        return any(token.upper() in upper_keyword for token in industry_token_list)

    def goto_public_page(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.alibaba_1688_page_timeout_ms)
            wait_for_page_timeout_with_jitter(page, 1200, 0.35, 700)
        except PlaywrightTimeoutError:
            logger.warning("1688 public page timeout, url=%s", url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("1688 public page navigation interrupted, url=%s, error=%s", url, self.clean_text(str(ex))[:160])
            wait_for_page_timeout_with_jitter(page, 1600, 0.35, 900)
        recovered_from_block = self.assert_public_page_allowed(page)
        if recovered_from_block:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.config.alibaba_1688_page_timeout_ms)
                wait_for_page_timeout_with_jitter(page, 1200, 0.35, 700)
            except PlaywrightTimeoutError:
                logger.warning("1688 public page retry timeout, url=%s", url)
            except PlaywrightError as ex:
                if not self.is_recoverable_navigation_error(ex):
                    raise
                logger.warning("1688 public page retry interrupted, url=%s, error=%s", url, self.clean_text(str(ex))[:160])
                wait_for_page_timeout_with_jitter(page, 1600, 0.35, 900)
            self.assert_public_page_allowed(page)

    def scroll_result_page_to_load(self, page) -> None:
        try:
            page.evaluate(
                """
                async () => {
                  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                  for (let index = 0; index < 6; index += 1) {
                    window.scrollBy(0, Math.max(700, window.innerHeight * 0.85));
                    await sleep(650);
                  }
                  window.scrollTo(0, 0);
                  await sleep(500);
                }
                """
            )
        except PlaywrightError:
            logger.warning("1688 result page scroll failed")

    def is_recoverable_navigation_error(self, ex: PlaywrightError) -> bool:
        message = str(ex)
        return (
            "net::ERR_ABORTED" in message
            or "frame was detached" in message
            or "interrupted by another navigation" in message
        )

    def assert_public_page_allowed(self, page) -> bool:
        blocked_reason = self.get_blocked_reason(page)
        if not blocked_reason:
            return False
        if self.is_feedback_page(page):
            if self.config.alibaba_1688_manual_verify_enabled:
                self.wait_for_manual_recovery(page, FEEDBACK_PAGE_MESSAGE)
                return True
            raise RuntimeError(f"{FEEDBACK_PAGE_MESSAGE}，已停止采集")
        if self.config.alibaba_1688_manual_verify_enabled:
            self.wait_for_manual_recovery(page, blocked_reason)
            return True
        raise RuntimeError(f"{blocked_reason}，已停止采集")

    def get_blocked_reason(self, page) -> str:
        page_url = page.url
        page_text = self.get_page_text(page)[:3000]
        if any(token in page_url for token in BLOCKED_URL_TOKEN_LIST):
            return "1688公开页面跳转到登录/验证页"
        if any(token in page_text for token in BLOCKED_TEXT_TOKEN_LIST):
            if self.looks_like_normal_1688_business_page(page_text, page_url):
                return ""
            return "1688公开页面出现验证要求"
        return ""

    @staticmethod
    def looks_like_normal_1688_business_page(page_text: str, page_url: str) -> bool:
        detail_matched_count = sum(1 for token in DETAIL_PAGE_TOKEN_LIST if token in page_text)
        is_1688_business_url = (
            "factory/card.html" in page_url
            or "sale.1688.com" in page_url
            or "company/" in page_url
        )
        has_normal_contact_area = (
            "电话联系" in page_text
            or "在线沟通" in page_text
            or "立即询价" in page_text
        )
        return is_1688_business_url and detail_matched_count >= 1 and has_normal_contact_area

    def is_feedback_page(self, page) -> bool:
        page_text = self.get_page_text(page)[:3000]
        matched_count = sum(1 for token in FEEDBACK_TEXT_TOKEN_LIST if token in page_text)
        return matched_count >= 2

    def wait_for_manual_recovery(self, page, blocked_reason: str) -> None:
        logger.warning("%s，等待人工恢复页面", blocked_reason)
        self.prepare_manual_login_recovery(page, blocked_reason)
        timeout_seconds = self.config.alibaba_1688_manual_verify_timeout_seconds
        poll_seconds = self.config.alibaba_1688_manual_verify_poll_seconds
        start_time = time.monotonic()
        while time.monotonic() - start_time <= timeout_seconds:
            page.wait_for_timeout(int(poll_seconds * 1000))
            if not self.is_feedback_page(page) and not self.get_blocked_reason(page):
                logger.info("1688页面已人工恢复，继续采集公开页面")
                self.emit_task_event(
                    "manual_resumed",
                    "info",
                    "1688扫码登录/人工验证已完成，继续采集公开页面。",
                )
                return
        raise RuntimeError(f"{blocked_reason}，人工恢复等待超时，已停止采集")

    def prepare_manual_login_recovery(self, page, blocked_reason: str) -> None:
        self.emit_task_event(
            "waiting_manual",
            "warning",
            f"{blocked_reason}；系统已退出当前 1688 登录态并打开官方登录页，请扫码登录。登录完成后保持页面打开，系统会自动继续采集。",
        )
        try:
            page.context.clear_cookies()
        except PlaywrightError:
            logger.warning("Could not clear 1688 cookies before manual login recovery")
        try:
            page.goto(
                ALIBABA_1688_LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=self.config.alibaba_1688_page_timeout_ms,
            )
        except PlaywrightTimeoutError:
            logger.warning("1688 manual login page timeout")
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("1688 manual login page navigation interrupted, error=%s", self.clean_text(str(ex))[:160])
        try:
            page.bring_to_front()
        except PlaywrightError:
            logger.warning("Could not bring 1688 page to front")

    def extract_raw_item_list(self, page) -> List[Dict]:
        return page.evaluate(
            """
            () => {
              const companyNamePattern = /[\\u4e00-\\u9fa5A-Za-z0-9（）()·\\-\\s]{2,80}?(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|商行|经营部|工作室|工厂|厂)/;
              const skipTextTokenList = [
                '首页', '我的阿里', '下载插件', '我的订单', '采购车', '消息', '官方服务', '开店',
                '简体中文', '以图搜款', '找货源', '找供应商', '工业品', '找服务', '找代发',
                '批量询价', '在线沟通', '立即询价', '实力榜', '服务榜', '采购助手'
              ];
              const skipHrefTokenList = [
                'offer/', 'offer_search', 'selloffer', 'detail.1688.com', 'login', 'passport',
                'factory_search', 'cart', 'purchase', 'trade', 'message', 'order', 'favorite',
                'service', 'plugin', 'market', 'activity'
              ];
              const normalizeText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
              const isVisible = (element) => {
                const rect = element.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              const likelyResultTokenList = [
                '主营', '响应率', '回头率', '履约率', '超级工厂', '实力商家', '源头工厂',
                '来样加工', '来图加工', 'OEM', 'ODM', '工厂', '加工', '批发', '供应链'
              ];
              const isLikelyResultCard = (element) => {
                if (!element) {
                  return false;
                }
                const rect = element.getBoundingClientRect();
                const text = normalizeText(element.innerText);
                if (rect.width < 320 || rect.height < 80 || rect.height > 560) {
                  return false;
                }
                if (text.length < 20 || text.length > 2200) {
                  return false;
                }
                if (!companyNamePattern.test(text)) {
                  return false;
                }
                return likelyResultTokenList.some((token) => text.includes(token));
              };
              const findCard = (element) => {
                let current = element;
                for (let depth = 0; current && depth < 10; depth += 1) {
                  if (isLikelyResultCard(current)) {
                    return current;
                  }
                  current = current.parentElement;
                }
                return null;
              };
              const isCandidateUrl = (href) => {
                if (!href) {
                  return false;
                }
                let url;
                try {
                  url = new URL(href, location.href);
                } catch (error) {
                  return false;
                }
                const host = url.hostname.toLowerCase();
                const path = url.pathname.toLowerCase();
                const hrefText = `${host}${path}`;
                if (!host.endsWith('1688.com')) {
                  return false;
                }
                if (host.startsWith('login.') || host.startsWith('passport.')) {
                  return false;
                }
                if (host === 'sale.1688.com' && path.includes('/factory/')) {
                  return true;
                }
                if (skipHrefTokenList.some((token) => hrefText.includes(token))) {
                  return false;
                }
                if (host.startsWith('s.') && !path.includes('/company/')) {
                  return false;
                }
                if (host.startsWith('factory.') || path.includes('factory') || path.includes('company')) {
                  return true;
                }
                if (['www.1688.com', 's.1688.com', 'detail.1688.com'].includes(host)) {
                  return false;
                }
                return /^[a-z0-9][a-z0-9-]*\\.1688\\.com$/.test(host);
              };
              const pickCardHref = (card, fallbackHref) => {
                const hrefList = Array.from(card.querySelectorAll('a[href]'))
                  .map((anchor) => anchor.href || '')
                  .filter(Boolean);
                const preferredHref = hrefList.find(isCandidateUrl);
                if (preferredHref) {
                  return new URL(preferredHref, location.href).href;
                }
                if (isCandidateUrl(fallbackHref)) {
                  return new URL(fallbackHref, location.href).href;
                }
                return '';
              };
              const categoryDenyTokenList = [
                '响应率', '履约率', '回头率', '金牌制造', '品牌制造', '批量询价',
                '来图加工', '来样加工', '包工包料', '支持', '认证', '质量控制',
                '服务榜', '实力榜', '热度榜', '新晋榜', '第1名', '第2名', '第3名', '第4名',
                '收藏', '采购', '消息', '联系', '员工', 'm²', '㎡'
              ];
              const categoryCityPattern = /^(广东|广州市?|深圳市?|东莞市?|佛山市?|中山市?|珠海市?|惠州市?|汕头市?|揭阳市?|江门市?|肇庆市?|清远市?|潮州市?)$/;
              const cleanCategoryLine = (line, companyName) => {
                let value = normalizeText(line);
                if (companyName) {
                  value = value.replace(companyName, ' ');
                }
                value = value
                  .replace(companyNamePattern, ' ')
                  .replace(/(?:超级工厂|实力工厂|源头工厂|工厂档案|诚信通|诚\\s*\\d+\\s*年)/g, ' ')
                  .replace(/\\d+(?:\\.\\d+)?\\s*(?:m²|㎡|m2|平米|平方米).*/g, ' ')
                  .replace(/\\d+\\s*-\\s*\\d+\\s*(?:人|员工).*/g, ' ')
                  .replace(/\\d+\\s*(?:人以下|员工以下|人|员工).*/g, ' ')
                  .replace(/\\d+\\s*%.*/g, ' ')
                  .replace(/[|｜]+/g, ' ')
                  .replace(/\\s+/g, ' ')
                  .trim();
                return value;
              };
              const isCategoryLine = (line) => {
                const value = normalizeText(line);
                if (value.length < 2 || value.length > 120) {
                  return false;
                }
                if (!/[\\u4e00-\\u9fa5A-Za-z]/.test(value)) {
                  return false;
                }
                if (companyNamePattern.test(value)) {
                  return false;
                }
                if (categoryCityPattern.test(value)) {
                  return false;
                }
                if (categoryDenyTokenList.some((token) => value.includes(token))) {
                  return false;
                }
                if (/^\\d+/.test(value)) {
                  return false;
                }
                return true;
              };
              const pickCardCategoryText = (card, companyName) => {
                const rawLines = (card.innerText || '')
                  .split(/\\n+/)
                  .map(normalizeText)
                  .filter(Boolean);
                const companyLineIndex = rawLines.findIndex((line) => (
                  (companyName && line.includes(companyName)) || companyNamePattern.test(line)
                ));
                const startIndex = companyLineIndex >= 0 ? companyLineIndex : 0;
                for (let index = startIndex; index < Math.min(rawLines.length, startIndex + 7); index += 1) {
                  const cleanLine = cleanCategoryLine(rawLines[index], companyName);
                  if (isCategoryLine(cleanLine)) {
                    return cleanLine;
                  }
                }
                const compactText = normalizeText(card.innerText || '');
                const metricMatch = compactText.match(/(?:\\d+\\s*%|\\d+(?:\\.\\d+)?\\s*(?:m²|㎡|m2|平米|平方米)|\\d+\\s*-\\s*\\d+\\s*(?:人|员工))/);
                if (!metricMatch) {
                  return '';
                }
                const beforeMetricText = compactText.slice(0, metricMatch.index);
                const cleanText = cleanCategoryLine(beforeMetricText, companyName);
                return isCategoryLine(cleanText) ? cleanText : '';
              };
              const allElementList = Array.from(document.querySelectorAll('body *')).slice(0, 2600);
              const cardList = [];
              for (const element of allElementList) {
                if (!isLikelyResultCard(element)) {
                  continue;
                }
                if (cardList.some((card) => card.contains(element) || element.contains(card))) {
                  continue;
                }
                element.setAttribute('data-codex-1688-card-index', `${cardList.length}`);
                cardList.push(element);
                if (cardList.length >= 120) {
                  break;
                }
              }
              const resultList = [];
              const seenKeySet = new Set();
              const anchorList = Array.from(document.querySelectorAll('a[href]')).slice(0, 1200);
              for (const element of anchorList) {
                if (!isVisible(element)) {
                  continue;
                }
                const text = normalizeText(element.innerText);
                const title = normalizeText(element.getAttribute('title'));
                const card = findCard(element);
                if (!card) {
                  continue;
                }
                const href = pickCardHref(card, element.href || '');
                if (!href) {
                  continue;
                }
                const parentText = normalizeText(card.innerText || '');
                const mergedText = `${text} ${title} ${parentText}`;
                if (!companyNamePattern.test(mergedText)) {
                  continue;
                }
                if (skipTextTokenList.some((token) => text === token || title === token || mergedText.startsWith(token))) {
                  continue;
                }
                const companyMatch = mergedText.match(companyNamePattern);
                const seenKey = `${href}|${companyMatch ? companyMatch[0].replace(/\\s+/g, '') : ''}`;
                if (seenKeySet.has(seenKey)) {
                  continue;
                }
                seenKeySet.add(seenKey);
                resultList.push({
                  href,
                  text,
                  title,
                  categoryText: pickCardCategoryText(card, companyMatch ? companyMatch[0].replace(/\\s+/g, '') : ''),
                  parentText: parentText.slice(0, 1600),
                  cardIndex: Number(card.getAttribute('data-codex-1688-card-index') || -1)
                });
                if (resultList.length >= 80) {
                  break;
                }
              }
              for (const card of cardList) {
                const parentText = normalizeText(card.innerText || '');
                const companyMatch = parentText.match(companyNamePattern);
                if (!companyMatch) {
                  continue;
                }
                const href = pickCardHref(card, '');
                const companyName = companyMatch[0].replace(/\\s+/g, '');
                const seenKey = `${href || 'card'}|${companyName}`;
                if (seenKeySet.has(seenKey)) {
                  continue;
                }
                seenKeySet.add(seenKey);
                resultList.push({
                  href,
                  text: companyName,
                  title: '',
                  categoryText: pickCardCategoryText(card, companyName),
                  parentText: parentText.slice(0, 1600),
                  cardIndex: Number(card.getAttribute('data-codex-1688-card-index') || -1)
                });
                if (resultList.length >= 100) {
                  break;
                }
              }
              return resultList;
            }
            """
        )

    def build_candidate(
        self,
        keyword: str,
        raw_item: Dict,
        industry: str,
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
    ) -> Optional[AlibabaCandidate]:
        raw_href = self.normalize_url(raw_item.get("href", ""))
        href = raw_href
        text = self.clean_text(raw_item.get("text", ""))
        title = self.clean_text(raw_item.get("title", ""))
        category_text = self.clean_text(raw_item.get("categoryText", ""))
        parent_text = self.clean_text(raw_item.get("parentText", ""))
        card_index = self.parse_int(raw_item.get("cardIndex", -1), -1)
        merged_text = " ".join([text, title, parent_text])
        company_name = self.extract_search_card_company_name(merged_text, keyword) or self.extract_search_card_display_company_name(
            parent_text,
            text,
            title,
        )
        if not company_name:
            self.record_candidate_reject("未识别企业名")
            return None
        if self.is_search_keyword_pseudo_company_name(company_name, keyword):
            self.record_candidate_reject("搜索词被误识别为企业名")
            return None
        profile_url = raw_href if self.is_valid_1688_url(raw_href) else ""
        if href and not self.is_company_or_factory_url(href):
            self.record_candidate_reject("详情链接不稳定，已按搜索页候选处理")
            href = ""
        product_name = self.extract_search_card_category_product_name(
            category_text,
            company_name,
        ) or self.extract_search_card_category_product_name(parent_text, company_name)
        return AlibabaCandidate(
            source_keyword=keyword,
            company_name=company_name,
            product_name=product_name,
            shop_url=self.pick_shop_url(href),
            profile_url=href or profile_url,
            raw_text=merged_text,
            card_index=card_index,
        )

    def is_target_city_card_text(self, target_city: str, text: str) -> bool:
        clean_target_city_list = self.normalize_target_city_list(target_city)
        if clean_target_city_list == [DEFAULT_GUANGDONG_TARGET_CITY]:
            return True
        compact_text = self.remove_inner_space(text)
        return any(city_name in compact_text or f"{city_name}市" in compact_text for city_name in clean_target_city_list)

    def enrich_candidate(self, page, candidate: AlibabaCandidate, industry: str) -> Optional[CollectedLeadDTO]:
        page_url = candidate.shop_url or candidate.profile_url
        detail_page = page
        should_close_detail_page = False
        phone_reveal_text = ""
        fallback_lead = self.build_fallback_lead_from_search_candidate(candidate, industry)
        try:
            if page_url:
                self.goto_public_page(detail_page, page_url)
            else:
                detail_page, should_close_detail_page = self.open_candidate_detail_from_search_page(page, candidate)
                if detail_page is None:
                    self.record_detail_reject("搜索页未找到可点击企业入口", candidate)
                    return fallback_lead
                page_url = detail_page.url
            self.expand_public_detail(detail_page)
            phone_reveal_text = self.reveal_public_phone(detail_page)
            if page_url and not self.is_same_1688_public_url(detail_page.url, page_url):
                self.goto_public_page(detail_page, page_url)
                self.expand_public_detail(detail_page)
        except RuntimeError:
            raise
        except PlaywrightError as ex:
            logger.warning("1688 detail page failed, url=%s, error=%s", page_url, ex)
            self.record_detail_reject("详情页打开失败", candidate)
            return fallback_lead
        page_text = self.clean_text(" ".join([self.get_page_text(detail_page), phone_reveal_text]))
        title_text = self.clean_text(detail_page.title())
        merged_text = " ".join([candidate.raw_text, title_text, page_text])
        company_name = candidate.company_name or self.extract_company_name(merged_text)
        if not company_name:
            self.record_detail_reject("未识别企业名", candidate)
            return None
        normalized_company_name = self.remove_inner_space(candidate.company_name)
        normalized_page_identity = self.remove_inner_space(f"{page_text} {title_text}")
        detail_company_name = self.extract_company_name(f"{title_text} {page_text}")
        if (
            detail_company_name
            and normalized_company_name
            and self.remove_inner_space(detail_company_name) != normalized_company_name
            and normalized_company_name not in normalized_page_identity
        ):
            self.record_detail_reject("详情页企业名不一致", candidate)
            return fallback_lead
        if (
            not self.is_keyword_relevant_text(candidate.source_keyword, industry, merged_text)
            and not self.is_keyword_relevant_text(candidate.source_keyword, industry, candidate.raw_text)
        ):
            self.record_detail_reject("行业关键词不匹配", candidate)
            return None
        if not self.is_candidate_guangdong_context(candidate, merged_text):
            self.record_detail_reject("无广东信号", candidate)
            return None
        product_name = candidate.product_name or self.extract_product_name(title_text, page_text[:120], candidate.source_keyword, company_name)
        phone_reveal_phone = self.extract_phone(phone_reveal_text)
        phone = phone_reveal_phone or self.extract_phone(merged_text)
        contact_name = self.extract_contact_name(merged_text)
        region_text = merged_text[:3000]
        if not is_guangdong_text(merged_text):
            region_text = f"1688广东筛选页 {region_text}"[:3000]
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            source_keyword=candidate.source_keyword,
            industry=industry,
            suspected_company_name=company_name,
            douyin_nickname="",
            product_name=product_name,
            contact_name=contact_name,
            phone=phone,
            phone_source="1688电话联系弹窗公开号码" if phone_reveal_phone else (
                "1688详情页公开电话" if phone else "1688详情页未展示公开电话"
            ),
            website_url="",
            shop_url=candidate.shop_url,
            profile_url=page_url,
            region_text=region_text,
            sample_video_url="",
            is_blue_v=False,
            is_enterprise_verified=self.is_enterprise_text(merged_text),
            recent_video_count_30d=0,
            recent_video_count_90d=0,
            commercial_keyword_count=self.count_business_keyword(merged_text),
        )
        if should_close_detail_page:
            detail_page.close()
        return lead

    def open_candidate_detail_from_search_page(self, page, candidate: AlibabaCandidate):
        if not candidate.search_url:
            return None, False
        self.goto_public_page(page, candidate.search_url)
        self.scroll_result_page_to_load(page)
        try:
            detail_page = self.click_candidate_company_entry(page, candidate)
            if detail_page is not None:
                detail_page.wait_for_load_state("domcontentloaded", timeout=self.config.alibaba_1688_page_timeout_ms)
                wait_for_page_timeout_with_jitter(detail_page, 1200, 0.35, 700)
                self.assert_public_page_allowed(detail_page)
                return detail_page, detail_page is not page
        except PlaywrightTimeoutError:
            logger.warning("1688 candidate detail click timeout, company=%s", candidate.company_name)
        except PlaywrightError as ex:
            logger.warning("1688 candidate detail click failed, company=%s, error=%s", candidate.company_name, ex)
        return None, False

    def click_candidate_company_entry(self, page, candidate: AlibabaCandidate):
        if self.assert_public_page_allowed(page):
            return None
        company_name = candidate.company_name
        if not company_name:
            return None
        locator_list = [
            page.locator(f"a:has-text('{company_name}')").first,
            page.get_by_text(company_name, exact=True).first,
            page.get_by_text(company_name, exact=False).first,
        ]
        if candidate.card_index >= 0:
            locator_list.insert(
                0,
                page.locator(f"[data-codex-1688-card-index='{candidate.card_index}'] a:has-text('{company_name}')").first,
            )
        for locator in locator_list:
            try:
                if locator.count() <= 0:
                    continue
                locator.scroll_into_view_if_needed(timeout=3000)
                try:
                    with page.expect_popup(timeout=2500) as popup_info:
                        locator.click(timeout=4000)
                    return popup_info.value
                except PlaywrightTimeoutError:
                    return page
            except PlaywrightError:
                continue
        return None

    def build_fallback_lead_from_search_candidate(
        self,
        candidate: AlibabaCandidate,
        industry: str,
    ) -> Optional[CollectedLeadDTO]:
        if not self.is_candidate_guangdong_context(candidate, candidate.raw_text):
            return None
        lead = self.build_lead_from_candidate_text(candidate, industry, SOURCE_TYPE_ALIBABA_1688)
        if lead is None:
            return None
        if not has_public_phone_text(lead.phone):
            lead.phone = "未公开"
            lead.phone_source = "1688搜索页未展示公开电话；详情页未采集到公开电话"
        if not is_guangdong_text(lead.region_text):
            lead.region_text = f"1688广东筛选页 {lead.region_text}"[:3000]
        return lead

    def record_detail_reject(self, reason: str, candidate: AlibabaCandidate) -> None:
        self.last_detail_reject_reason_count[reason] = self.last_detail_reject_reason_count.get(reason, 0) + 1
        logger.info(
            "1688 detail rejected, reason=%s, company=%s, keyword=%s, url=%s",
            reason,
            candidate.company_name,
            candidate.source_keyword,
            candidate.shop_url or candidate.profile_url,
        )

    def format_detail_reject_reason(self) -> str:
        if not self.last_detail_reject_reason_count:
            return ""
        reason_text = "，".join(
            f"{reason} {count} 个"
            for reason, count in sorted(self.last_detail_reject_reason_count.items(), key=lambda item: item[0])
        )
        return f"详情页拦截原因：{reason_text}。"

    def record_candidate_reject(self, reason: str) -> None:
        self.last_candidate_reject_reason_count[reason] = self.last_candidate_reject_reason_count.get(reason, 0) + 1

    def record_public_lead_reject(self, reason: str) -> None:
        clean_reason = self.clean_text(reason) or "公开线索被过滤"
        self.last_public_lead_reject_reason_count[clean_reason] = (
            self.last_public_lead_reject_reason_count.get(clean_reason, 0) + 1
        )

    def format_candidate_reject_reason(self) -> str:
        if not self.last_candidate_reject_reason_count:
            return ""
        reason_text = "，".join(
            f"{reason} {count} 个"
            for reason, count in sorted(self.last_candidate_reject_reason_count.items(), key=lambda item: item[0])
        )
        return f"候选过滤原因：{reason_text}。"

    def format_public_lead_reject_reason(self) -> str:
        if not self.last_public_lead_reject_reason_count:
            return ""
        reason_text = "，".join(
            f"{reason} {count} 条"
            for reason, count in sorted(self.last_public_lead_reject_reason_count.items(), key=lambda item: item[0])
        )
        return f"入库前过滤原因：{reason_text}。"

    def format_no_saved_lead_reason(self) -> str:
        reason_list = []
        if self.last_existing_skip_count:
            reason_list.append(f"已存在/重复线索 {self.last_existing_skip_count} 条")
        if self.last_run_dedupe_skip_count:
            reason_list.append(f"本批重复候选 {self.last_run_dedupe_skip_count} 条")
        if self.last_repeated_search_page_guard_count:
            reason_list.append("1688返回重复结果页，已自动停止无效翻页")
        if self.last_public_lead_reject_reason_count:
            reason_list.append(self.format_public_lead_reject_reason().rstrip("。"))
        if not reason_list:
            reason_list.append("搜索页候选没有生成可入库线索")
        return "；".join(reason_list) + "。"

    def is_candidate_guangdong_context(self, candidate: AlibabaCandidate, merged_text: str) -> bool:
        explicit_candidate_text = " ".join(
            [
                candidate.company_name,
                candidate.product_name,
                candidate.raw_text,
                candidate.shop_url,
                candidate.profile_url,
            ]
        )
        if has_non_guangdong_province_text(explicit_candidate_text):
            return False
        candidate_text = " ".join([candidate.source_keyword, explicit_candidate_text])
        if is_guangdong_text(candidate_text):
            return True
        if self.is_guangdong_filtered_search_url(candidate.search_url):
            return True
        return is_guangdong_text(self.extract_guangdong_identity_text(merged_text))

    def extract_guangdong_identity_text(self, text: str) -> str:
        clean_text = self.clean_text(text)
        if not clean_text:
            return ""
        token_list = ["地址", "所在地区", "广东", "广州", "深圳", "佛山", "东莞", "中山", "汕头", "珠海", "惠州"]
        chunk_list = []
        for token in token_list:
            start_index = clean_text.find(token)
            if start_index < 0:
                continue
            chunk_list.append(clean_text[max(0, start_index - 120) : start_index + 260])
        return " ".join(chunk_list)

    def expand_public_detail(self, page) -> None:
        if self.assert_public_page_allowed(page):
            return
        try:
            page.evaluate(
                """
                () => {
                  const tokenList = ['查看更多', '展开', '工厂档案', '工厂展厅'];
                  const blockedTextTokenList = ['在线沟通', '立即询价', '批量询价', '采购车', '消息', '以图搜款', '服务榜', '实力榜'];
                  const getClickableElement = (element) => element.closest('button,a,[role="button"]') || element;
                  const elementList = Array.from(document.querySelectorAll('button,a,[role="button"],span'));
                  for (const element of elementList) {
                    const text = (element.innerText || '').trim();
                    if (!tokenList.some((token) => text.includes(token))) {
                      continue;
                    }
                    if (blockedTextTokenList.some((token) => text.includes(token))) {
                      continue;
                    }
                    const clickableElement = getClickableElement(element);
                    if (clickableElement.tagName === 'A' && clickableElement.href) {
                      try {
                        const targetUrl = new URL(clickableElement.href, location.href);
                        if (targetUrl.hostname !== location.hostname) {
                          continue;
                        }
                      } catch (error) {
                        continue;
                      }
                    }
                    const rect = element.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) {
                      continue;
                    }
                    try {
                      element.scrollIntoView({ block: 'center', inline: 'center' });
                      clickableElement.click();
                    } catch (error) {
                      // Ignore elements that are visible but not clickable.
                    }
                  }
                }
                """
            )
            page.wait_for_timeout(900)
        except PlaywrightError:
            logger.warning("1688 detail expand failed")

    def _legacy_reveal_public_phone(self, page) -> None:
        if self.click_visible_text_button(
            page,
            ["电话联系", "查看电话", "联系手机", "联系电话"],
            ["在线沟通", "立即询价", "批量询价", "扫码联系"],
        ):
            page.wait_for_timeout(2200)
            self.assert_public_page_allowed(page)
            return
        try:
            clicked = page.evaluate(
                """
                async () => {
                  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                  const tokenList = ['电话联系', '查看电话', '联系手机', '联系电话'];
                  const blockedTextTokenList = ['在线沟通', '立即询价', '批量询价', '扫码联系'];
                  const getClickableElement = (element) => element.closest('button,a,[role="button"]') || element;
                  const elementList = Array.from(document.querySelectorAll('button,a,[role="button"],span'));
                  for (const element of elementList) {
                    const text = (element.innerText || '').replace(/\\s+/g, '');
                    if (!tokenList.some((token) => text.includes(token))) {
                      continue;
                    }
                    if (blockedTextTokenList.some((token) => text.includes(token))) {
                      continue;
                    }
                    const clickableElement = getClickableElement(element);
                    if (clickableElement.tagName === 'A' && clickableElement.href) {
                      try {
                        const targetUrl = new URL(clickableElement.href, location.href);
                        if (targetUrl.hostname !== location.hostname) {
                          continue;
                        }
                      } catch (error) {
                        continue;
                      }
                    }
                    const rect = element.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) {
                      continue;
                    }
                    element.scrollIntoView({ block: 'center', inline: 'center' });
                    await sleep(500);
                    clickableElement.click();
                    return true;
                  }
                  return false;
                }
                """
            )
            if clicked:
                page.wait_for_timeout(2000)
                self.assert_public_page_allowed(page)
        except PlaywrightError:
            logger.warning("1688 phone reveal click failed")

    def reveal_public_phone(self, page) -> str:
        if self.assert_public_page_allowed(page):
            return ""
        token_list = ["电话联系", "查看电话", "联系手机", "联系电话", "公开电话", "拨打电话"]
        blocked_text_token_list = ["在线沟通", "立即询价", "批量询价", "扫码联系", "采购车", "消息"]
        clicked = self.click_visible_text_button(page, token_list, blocked_text_token_list)
        if not clicked:
            try:
                clicked = page.evaluate(
                    """
                    async ({ tokenList, blockedTextTokenList }) => {
                      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                      const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none'
                          && style.visibility !== 'hidden'
                          && Number(style.opacity) !== 0
                          && rect.width > 0
                          && rect.height > 0;
                      };
                      const getClickableElement = (element) => element.closest('button,a,[role="button"]') || element;
                      const elementList = Array.from(document.querySelectorAll('button,a,[role="button"],span,div'));
                      for (const element of elementList) {
                        const text = (element.innerText || '').replace(/\\s+/g, '');
                        if (!tokenList.some((token) => text.includes(token))) {
                          continue;
                        }
                        if (blockedTextTokenList.some((token) => text.includes(token))) {
                          continue;
                        }
                        const clickableElement = getClickableElement(element);
                        if (clickableElement.tagName === 'A' && clickableElement.href) {
                          try {
                            const targetUrl = new URL(clickableElement.href, location.href);
                            if (targetUrl.hostname !== location.hostname) {
                              continue;
                            }
                          } catch (error) {
                            continue;
                          }
                        }
                        if (!isVisible(element) || !isVisible(clickableElement)) {
                          continue;
                        }
                        element.scrollIntoView({ block: 'center', inline: 'center' });
                        await sleep(500);
                        clickableElement.click();
                        return true;
                      }
                      return false;
                    }
                    """,
                    {"tokenList": token_list, "blockedTextTokenList": blocked_text_token_list},
                )
            except PlaywrightError:
                logger.warning("1688 phone reveal click failed")
                clicked = False
        if not clicked:
            return ""
        for _ in range(12):
            page.wait_for_timeout(500)
            self.assert_public_page_allowed(page)
            overlay_text = self.clean_text(self.get_visible_overlay_text(page))
            if self.extract_phone(overlay_text):
                return overlay_text
        return self.clean_text(self.get_visible_overlay_text(page))

    def get_visible_overlay_text(self, page) -> str:
        try:
            return page.evaluate(
                """
                () => {
                  const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && Number(style.opacity) !== 0
                      && rect.width > 0
                      && rect.height > 0;
                  };
                  const selectorList = [
                    '[role="dialog"]',
                    '.dialog',
                    '.modal',
                    '.popup',
                    '.next-dialog',
                    '.rax-dialog',
                    '[class*="dialog"]',
                    '[class*="modal"]',
                    '[class*="popup"]',
                    '[class*="phone"]',
                    '[class*="contact"]'
                  ];
                  const textList = Array.from(document.querySelectorAll(selectorList.join(',')))
                    .filter(isVisible)
                    .map((element) => (element.innerText || '').trim())
                    .filter(Boolean);
                  return Array.from(new Set(textList)).join('\\n');
                }
                """
            )
        except PlaywrightError:
            return ""

    def build_lead_from_candidate_text(
        self,
        candidate: AlibabaCandidate,
        industry: str,
        source_type: str = SOURCE_TYPE_ALIBABA_1688,
    ) -> Optional[CollectedLeadDTO]:
        merged_text = self.clean_text(candidate.raw_text)
        company_name = candidate.company_name or self.extract_company_name(merged_text)
        if not company_name:
            return None
        product_name = candidate.product_name or self.extract_product_name(
            merged_text[:120],
            "",
            candidate.source_keyword,
            company_name,
        )
        phone = self.extract_phone(merged_text)
        return CollectedLeadDTO(
            source_type=source_type,
            source_keyword=candidate.source_keyword,
            industry=industry,
            suspected_company_name=company_name,
            product_name=product_name,
            contact_name=self.extract_contact_name(merged_text),
            phone=phone,
            phone_source="1688当前页面公开字段" if phone else "",
            shop_url=candidate.shop_url,
            profile_url=candidate.profile_url or candidate.shop_url or candidate.search_url,
            region_text=merged_text[:3000],
            is_enterprise_verified=self.is_enterprise_text(merged_text),
            commercial_keyword_count=self.count_business_keyword(merged_text),
        )

    def get_page_text(self, page) -> str:
        try:
            return page.locator("body").inner_text(timeout=5000)
        except PlaywrightError:
            return ""

    def extract_company_name(self, text: str) -> str:
        for match in COMPANY_NAME_PATTERN.finditer(text):
            company_name = clean_company_name_text(match.group(1))
            if self.is_valid_company_name(company_name):
                return company_name
        return ""

    def extract_search_card_company_name(self, text: str, keyword: str) -> str:
        for match in COMPANY_NAME_PATTERN.finditer(text or ""):
            company_name = clean_company_name_text(match.group(1))
            if self.is_search_keyword_pseudo_company_name(company_name, keyword):
                continue
            if self.is_valid_company_name(company_name):
                return company_name
        return ""

    def is_search_keyword_pseudo_company_name(self, company_name: str, keyword: str) -> bool:
        clean_name = self.remove_inner_space(clean_company_name_text(company_name))
        clean_keyword = self.remove_inner_space(self.clean_1688_search_keyword(keyword))
        if not clean_name:
            return True
        if clean_keyword and clean_name == clean_keyword:
            return not str(keyword or "").strip().endswith(REAL_COMPANY_STRONG_SUFFIX_TUPLE)
        return bool(KEYWORD_ONLY_COMPANY_PATTERN.fullmatch(clean_name))

    def extract_search_card_display_company_name(self, parent_text: str, text: str = "", title: str = "") -> str:
        for value in [text, title]:
            clean_value = self.clean_text(value)
            if self.is_valid_1688_display_company_name(clean_value):
                return clean_value[:80]
        clean_parent_text = self.clean_text(parent_text)
        if not clean_parent_text:
            return ""
        city_pattern = (
            r"北京|上海|天津|重庆|广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|"
            r"揭阳|江门|肇庆|清远|潮州|杭州|宁波|温州|义乌|金华|绍兴|苏州|"
            r"南通|泉州|厦门|福州|衡阳|西安"
        )
        marker_pattern = r"(?:超级工厂|实力工厂|源头工厂|工厂档案|诚信通|诚\s*\d+\s*年|\d+\s*年)"
        pattern_list = [
            rf"^(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{{4,60}}?)\s+(?:{city_pattern})\s+{marker_pattern}",
            rf"^(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{{4,60}}?)\s+{marker_pattern}",
        ]
        for pattern in pattern_list:
            match = re.search(pattern, clean_parent_text)
            if not match:
                continue
            candidate_name = self.clean_text(match.group("name"))
            if self.is_valid_1688_display_company_name(candidate_name):
                return candidate_name[:80]
        return ""

    def is_valid_1688_display_company_name(self, company_name: str) -> bool:
        clean_name = self.clean_text(company_name)
        compact_name = self.remove_inner_space(clean_name)
        if not self.is_valid_company_name(clean_name):
            return False
        if len(compact_name) < 6 or len(compact_name) > 60:
            return False
        if re.search(r"\d+\s*年|\d+\s*%|\d+(?:\.\d+)?\s*(?:m²|㎡|m2|平米|平方米)", clean_name):
            return False
        deny_token_list = [
            "响应率",
            "履约率",
            "回头率",
            "来图加工",
            "清加工",
            "可开专票",
            "批量询价",
            "产品信息",
            "公司信息",
        ]
        if has_any_token(clean_name, deny_token_list):
            return False
        target_token_list = [
            "服饰",
            "服装",
            "制衣",
            "纺织",
            "针织",
            "鞋",
            "帽",
            "箱包",
            "皮具",
            "电子",
            "数码",
            "电器",
            "科技",
            "塑胶",
            "五金",
        ]
        region_token_list = [
            "市",
            "区",
            "县",
            "镇",
            "街道",
            "广州",
            "深圳",
            "东莞",
            "佛山",
            "中山",
            "揭阳",
            "汕头",
            "珠海",
            "惠州",
        ]
        return has_any_token(clean_name, target_token_list) and has_any_token(clean_name, region_token_list)

    def is_valid_company_name(self, company_name: str) -> bool:
        if not company_name:
            return False
        if company_name in INVALID_COMPANY_NAME_SET:
            return False
        if re.search(r"(省|市|区|县|镇|街道)[)）]", company_name):
            return False
        if company_name.count("(") != company_name.count(")") or company_name.count("（") != company_name.count("）"):
            return False
        if len(company_name) < 4:
            return False
        if company_name.endswith(("工厂", "厂")) and len(company_name) < 6:
            return False
        return True

    def extract_product_name(self, text: str, title: str, keyword: str, company_name: str) -> str:
        for value in [title, text]:
            clean_value = self.normalize_1688_card_category_product(
                self.clean_product_text(value, company_name),
                company_name,
            )
            if clean_value:
                return clean_value
        return ""

    def extract_search_card_category_product_name(self, parent_text: str, company_name: str) -> str:
        text = self.clean_text(parent_text)
        if not text:
            return ""
        marked_category = self.extract_1688_card_category_between_markers(text, company_name)
        if marked_category:
            normalized_category = self.normalize_1688_card_category_product(marked_category, company_name)
            if normalized_category:
                return normalized_category
        segment_list = re.split(r"[|｜]+", text)
        for segment in segment_list:
            clean_segment = self.clean_1688_card_category_segment(segment, company_name)
            normalized_category = self.normalize_1688_card_category_product(clean_segment, company_name)
            if normalized_category:
                return normalized_category[:80]
        return ""

    def normalize_1688_card_category_product(self, value: str, company_name: str = "") -> str:
        token_list = []
        for token in self.split_1688_card_category_tokens(value):
            clean_token = self.clean_1688_card_category_segment(token, company_name)
            if not self.is_1688_card_category_segment(clean_token):
                continue
            append_unique_text(token_list, clean_token)
            if len(token_list) >= 4:
                break
        return "、".join(token_list)

    def split_1688_card_category_tokens(self, value: str) -> List[str]:
        normalized_value = self.clean_text(value)
        normalized_value = re.sub(r"[、,，|｜]+", " ", normalized_value)
        return [token.strip() for token in normalized_value.split() if token.strip()]

    def extract_1688_card_category_between_markers(self, parent_text: str, company_name: str) -> str:
        text = self.clean_text(parent_text)
        if company_name:
            text = text.replace(company_name, " ")
        marker_pattern = r"(?:超级工厂|实力工厂|源头工厂|工厂档案|诚信通|诚\s*\d+\s*年)"
        end_pattern = (
            r"(?=\s+\d+(?:\.\d+)?\s*(?:m²|㎡|m2|平米|平方米)"
            r"|\s+\d+\s*-\s*\d+\s*人"
            r"|\s+\d+\s*人以下"
            r"|\s+金牌制造"
            r"|\s+\d+\s*%|\s+响应率|\s+履约率|\s+回头率|$)"
        )
        pattern = re.compile(
            marker_pattern
            + r"(?:\s+"
            + marker_pattern
            + r")*\s+(?P<category>[\u4e00-\u9fa5A-Za-z0-9、/，,（）()·\-\s]{2,100}?)"
            + end_pattern
        )
        for match in pattern.finditer(text):
            category = self.clean_1688_card_category_segment(match.group("category"), "")
            normalized_category = self.normalize_1688_card_category_product(category, company_name)
            if normalized_category:
                return normalized_category[:80]
        return ""

    def clean_1688_card_category_segment(self, segment: str, company_name: str) -> str:
        value = self.clean_text(segment)
        if company_name:
            value = value.replace(company_name, " ")
        value = re.sub(r"(超级工厂|实力工厂|源头工厂|工厂档案|诚信通|诚\s*\d+\s*年)", " ", value)
        value = re.sub(r"(广东|广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|揭阳|江门|肇庆|清远|潮州|深圳市|东莞市|佛山市|广州市|揭阳市)", " ", value)
        value = re.sub(r"\d+(?:\.\d+)?\s*(?:m²|㎡|m2|平米|平方米)", " ", value)
        value = re.sub(r"\d+\s*-\s*\d+\s*(?:人|员工)", " ", value)
        value = re.sub(r"\d+\s*(?:人以下|员工以下|人|员工)", " ", value)
        value = re.sub(r"\d+\s*%[^ |｜]{0,8}", " ", value)
        value = self.clean_text(value)
        return value.strip(" -_|,，、;；。")

    def is_1688_card_category_segment(self, value: str) -> bool:
        clean_value = self.clean_text(value)
        compact_value = self.remove_inner_space(clean_value)
        if len(compact_value) < 2 or len(compact_value) > 80:
            return False
        if not re.search(r"[\u4e00-\u9fa5A-Za-z]", clean_value):
            return False
        if COMPANY_NAME_PATTERN.search(clean_value):
            return False
        deny_token_list = [
            "响应率",
            "履约率",
            "回头率",
            "金牌制造",
            "品牌制造",
            "包工包料",
            "来图加工",
            "来样加工",
            "可开专票",
            "质量控制",
            "支持外贸订单",
            "批量询价",
            "在线交易",
            "CCC认证",
            "RoHS认证",
            "3CE",
            "CE认证",
            "ISO",
            "诚信等级",
            "纳税人",
            "生产实力",
            "供应商",
            "支持贴牌",
            "贴牌加工",
            "税人",
            "布料",
        ]
        if has_any_token(clean_value, deny_token_list):
            return False
        if re.search(r"\d+(?:\.\d+)?\s*(?:m²|㎡|m2|平米|平方米)|\d+\s*-\s*\d+\s*(?:人|员工)|\d+\s*(?:人以下|员工以下|人|员工)|\d+\s*%", clean_value):
            return False
        short_product_token_list = [
            "服",
            "装",
            "衣",
            "衫",
            "恤",
            "裤",
            "裙",
            "袍",
            "套",
            "鞋",
            "帽",
            "包",
            "壳",
            "扑",
            "蛋",
            "T恤",
            "Polo",
            "背心",
            "裹胸",
            "抹胸",
            "手机",
            "配件",
            "数码",
            "电器",
            "电池",
            "蓝牙",
            "充电",
            "充电器",
            "充电线",
            "耳机",
            "音响",
            "音箱",
            "扬声器",
            "喇叭",
            "线材",
            "数据线",
            "连接线",
            "电源",
            "贴膜",
            "支架",
            "手机壳",
            "保护套",
            "自拍",
            "键盘",
            "鼠标",
            "键鼠",
            "游戏",
            "手柄",
            "电竞",
            "耳麦",
            "美容",
            "护理",
            "护肤",
            "护肤品",
            "美妆",
            "面膜",
            "敷料",
            "化妆",
            "爽肤",
            "乳液",
            "精华",
            "眼部",
            "面部",
            "身体",
        ]
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", compact_value) and not has_any_token(clean_value, short_product_token_list):
            return False
        return True

    def extract_phone(self, text: str) -> str:
        return clean_public_phone_text(text, include_service=False)

    @staticmethod
    def dedupe_phone_list(phone_list: List[str]) -> List[str]:
        return dedupe_public_phone_list(phone_list)

    def extract_contact_name(self, text: str) -> str:
        return extract_contact_name_by_pattern(text)

    def is_enterprise_text(self, text: str) -> bool:
        return any(token in text for token in ["有限公司", "诚信通", "实力商家", "源头工厂", "工厂档案"])

    def count_business_keyword(self, text: str) -> int:
        return sum(1 for keyword in BUSINESS_KEYWORD_LIST if keyword in text)

    def pick_shop_url(self, href: str) -> str:
        parsed_url = urlparse(href)
        host = parsed_url.netloc.lower()
        if host == "sale.1688.com":
            return href
        platform_host_prefix_list = ("s.", "detail.", "factory.", "www.", "login.", "passport.")
        if host.endswith(".1688.com") and not host.startswith(platform_host_prefix_list):
            return f"{parsed_url.scheme}://{parsed_url.netloc}/"
        return href

    def normalize_url(self, url: str) -> str:
        clean_url = url.strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        return clean_url

    @staticmethod
    def is_same_1688_public_url(left_url: str, right_url: str) -> bool:
        left = urlparse(left_url or "")
        right = urlparse(right_url or "")
        return (
            left.netloc.lower() == right.netloc.lower()
            and left.path.rstrip("/") == right.path.rstrip("/")
        )

    @staticmethod
    def parse_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def is_valid_1688_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        parsed_url = urlparse(url)
        host = parsed_url.netloc.lower()
        if not host.endswith("1688.com"):
            return False
        return not any(token in host for token in ["login", "passport", "cart", "purchase", "trade"])

    def is_company_or_factory_url(self, url: str) -> bool:
        if not self.is_valid_1688_url(url):
            return False
        parsed_url = urlparse(url)
        host = parsed_url.netloc.lower()
        path = parsed_url.path.lower()
        url_text = f"{host}{path}"
        if host.startswith(("login.", "passport.", "cart.", "trade.")):
            return False
        if host == "sale.1688.com" and "factory" in path:
            return True
        if any(token in url_text for token in ALIBABA_1688_CANDIDATE_DENY_URL_TOKEN_LIST):
            return False
        if host.startswith("s.") and "company" in path:
            return True
        if host.startswith("s."):
            return False
        if host.startswith("factory.") or "factory" in path or "company" in path:
            return True
        if host in {"www.1688.com", "s.1688.com", "detail.1688.com"}:
            return False
        return bool(re.match(r"^[a-z0-9][a-z0-9-]*\.1688\.com$", host))

    def is_keyword_relevant_text(self, keyword: str, industry: str, text: str) -> bool:
        clean_text = self.clean_text(text).upper()
        if not clean_text:
            return False
        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [])
        has_industry_token = True
        if industry_token_list:
            has_industry_token = any(token.upper() in clean_text for token in industry_token_list)
        if not has_industry_token:
            return False

        affinity_token_list = self.build_keyword_affinity_token_list(keyword)
        if affinity_token_list and not any(token.upper() in clean_text for token in affinity_token_list):
            return False

        business_token_list = self.build_keyword_business_token_list(keyword)
        keyword_token_list = self.build_keyword_core_token_list(keyword, industry)
        if keyword_token_list:
            has_keyword_token = any(token.upper() in clean_text for token in keyword_token_list)
            if business_token_list:
                has_business_token = any(token.upper() in clean_text for token in business_token_list)
                return has_keyword_token and has_business_token
            return has_keyword_token

        if business_token_list:
            return any(token.upper() in clean_text for token in business_token_list)
        return True

    def is_search_result_card_relevant(self, keyword: str, industry: str, text: str) -> bool:
        clean_text = self.clean_text(text).upper()
        if not clean_text:
            return False

        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [])
        if industry_token_list and not any(token.upper() in clean_text for token in industry_token_list):
            return False
        affinity_token_list = self.build_keyword_affinity_token_list(keyword)
        if affinity_token_list and not any(token.upper() in clean_text for token in affinity_token_list):
            return False
        if re.search(r"诚\s*\d+\s*年|\d+\s*年|响应率|履约率|回头率|超级工厂|实力工厂|源头工厂", clean_text, flags=re.IGNORECASE):
            return True

        keyword_token_list = self.build_keyword_core_token_list(keyword, industry)
        if keyword_token_list and any(token.upper() in clean_text for token in keyword_token_list):
            return True

        return any(token.upper() in clean_text for token in BUSINESS_KEYWORD_LIST)

    def build_keyword_business_token_list(self, keyword: str) -> List[str]:
        clean_keyword = self.clean_text(keyword)
        if not clean_keyword:
            return []
        token_list = []
        for token in BUSINESS_KEYWORD_LIST:
            if token and token in clean_keyword:
                token_list.append(token)
        return self.dedupe_text_list(token_list)

    def build_keyword_affinity_token_list(self, keyword: str) -> List[str]:
        if self.is_specific_company_search_keyword(keyword):
            return []
        clean_keyword = self.remove_leading_guangdong_region_token(keyword)
        for generic_token in sorted(GENERIC_1688_KEYWORD_TOKEN_LIST, key=len, reverse=True):
            clean_keyword = clean_keyword.replace(generic_token, "")
        compact_keyword = self.remove_inner_space(clean_keyword)
        for trigger_token_list, affinity_token_list in ALIBABA_1688_KEYWORD_AFFINITY_GROUP_LIST:
            if any(token.upper() in compact_keyword.upper() for token in trigger_token_list):
                return list(affinity_token_list)
        if compact_keyword.upper() in {token.upper() for token in ALIBABA_1688_BROAD_KEYWORD_SET}:
            return []
        if len(compact_keyword) >= 2:
            return [compact_keyword]
        return []

    def build_keyword_core_token_list(self, keyword: str, industry: str) -> List[str]:
        clean_keyword = self.clean_text(keyword)
        if not clean_keyword:
            return []
        token_list = []
        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [])
        for token in industry_token_list:
            if token and token in clean_keyword:
                token_list.append(token)
        reduced_keyword = clean_keyword
        for generic_token in GENERIC_1688_KEYWORD_TOKEN_LIST:
            reduced_keyword = reduced_keyword.replace(generic_token, " ")
        for token in re.split(r"[,，、/|;\s]+", reduced_keyword):
            clean_token = token.strip()
            if len(clean_token) >= 2:
                token_list.append(clean_token)
        return self.dedupe_text_list(token_list)

    def is_industry_relevant_text(self, industry: str, text: str) -> bool:
        token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [])
        if not token_list:
            return True
        return any(token.upper() in text for token in token_list)

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result_list = []
        dedupe_set = set()
        for text in text_list:
            clean_text = self.clean_text(text)
            if not clean_text or clean_text in dedupe_set:
                continue
            dedupe_set.add(clean_text)
            result_list.append(clean_text)
        return result_list

    def clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def remove_inner_space(self, text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    def click_visible_text_button(self, page, token_list: List[str], blocked_text_token_list: List[str]) -> bool:
        selector = "button,a,[role='button'],span,div"
        for token in token_list:
            try:
                locator = page.locator(selector).filter(has_text=token)
                count = min(locator.count(), 12)
                for index in range(count):
                    element = locator.nth(index)
                    try:
                        if not element.is_visible(timeout=800):
                            continue
                        text = self.clean_text(element.inner_text(timeout=800))
                        if not text or token not in text:
                            continue
                        if any(blocked_text in text for blocked_text in blocked_text_token_list):
                            continue
                        element.scroll_into_view_if_needed(timeout=2500)
                        page.wait_for_timeout(450)
                        element.click(timeout=3000)
                        return True
                    except PlaywrightError:
                        continue
            except PlaywrightError:
                continue
        return False

    def clean_product_text(self, text: str, company_name: str) -> str:
        value = self.clean_text(text)
        if self.contains_mojibake(value):
            return ""
        value = value.replace(company_name, "").strip()
        value = re.sub(r"(1688|阿里巴巴|批发网|厂家|供应商|首页|登录|注册)", "", value, flags=re.IGNORECASE)
        return value.strip(" -_|,，。")

    def contains_mojibake(self, text: str) -> bool:
        return any(token in (text or "") for token in MOJIBAKE_TOKEN_LIST)

    def normalize_dedupe_text(self, text: str) -> str:
        clean_text = self.clean_text(text)
        return re.sub(r"[\s,，。；;、/\\|（）()【】\[\]{}<>《》\"'`]+", "", clean_text).upper()

    def dedupe_candidate_list(self, candidate_list: List[AlibabaCandidate]) -> List[AlibabaCandidate]:
        result_list = []
        dedupe_set = set()
        for candidate in candidate_list:
            dedupe_key = self.normalize_dedupe_text(candidate.company_name or candidate.shop_url or candidate.profile_url)
            if not dedupe_key or dedupe_key in dedupe_set:
                continue
            dedupe_set.add(dedupe_key)
            result_list.append(candidate)
        return result_list

    def build_dedupe_key(self, lead: CollectedLeadDTO) -> str:
        return (
            self.normalize_dedupe_text(lead.suspected_company_name)
            or self.normalize_dedupe_text(lead.shop_url)
            or self.normalize_dedupe_text(lead.profile_url)
            or self.normalize_dedupe_text(f"{lead.source_keyword}:{lead.product_name}")
        )

    def wait_between_page(self) -> None:
        sleep_with_jitter(self.config.alibaba_1688_request_interval_seconds, 0.4, 8.0)

    def wait_before_detail_visit(self) -> None:
        wait_seconds = max(8.0, self.config.alibaba_1688_request_interval_seconds * 0.8)
        sleep_with_jitter(wait_seconds, 0.35, 6.0)


class MadeInChinaPublicPageCollector(Alibaba1688PublicPageCollector):
    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        self.reset_collect_diagnostic()
        clean_keyword_list = self.build_search_keyword_list(industry, keywords)
        self.last_search_keyword_list = clean_keyword_list
        if collect_limit <= 0:
            raise RuntimeError("中国制造网采集数量必须大于 0，请重新设置采集数量。")
        if not clean_keyword_list:
            raise RuntimeError(
                f"中国制造网采集关键词无效：当前行业为“{industry}”，请填写与行业相关的产品词，例如“手机壳工厂、数据线厂家”。"
            )

        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        with sync_playwright() as playwright:
            browser_session = self.create_browser_session(playwright)
            context = browser_session.context
            page = context.new_page()
            try:
                for keyword in clean_keyword_list:
                    if len(result_list) >= collect_limit:
                        break
                    candidate_search_limit = self.build_search_candidate_limit(collect_limit - len(result_list))
                    candidate_list = self.search_candidate(page, keyword, candidate_search_limit, industry)
                    for candidate in candidate_list:
                        if len(result_list) >= collect_limit:
                            break
                        lead = self.build_lead_from_candidate(candidate, industry)
                        if lead is None:
                            continue
                        dedupe_key = self.build_dedupe_key(lead)
                        if dedupe_key in dedupe_key_set:
                            continue
                        if self.is_existing_lead(lead):
                            continue
                        dedupe_key_set.add(dedupe_key)
                        result_list.append(lead)
                        self.remember_collected_lead_identity(lead)
                        self.wait_after_collected_lead(len(result_list), collect_limit)
            finally:
                context.close()
                if browser_session.browser is not None:
                    browser_session.browser.close()
        if not result_list:
            self.last_collect_diagnostic = self.build_empty_collect_diagnostic()
        return result_list

    def build_empty_collect_diagnostic(self) -> str:
        keyword_text = "、".join(self.last_search_keyword_list) if self.last_search_keyword_list else "无有效关键词"
        if self.last_raw_item_count == 0:
            return (
                f"中国制造网本次未采集到公司信息：实际搜索词为“{keyword_text}”，搜索页没有解析到企业卡片。"
                "请确认已完成中国制造网登录/验证码，并且地区筛选能切到华南。"
            )
        if self.last_candidate_count == 0:
            return (
                f"中国制造网本次未采集到公司信息：搜索页解析到 {self.last_raw_item_count} 个可见块，"
                f"但没有通过公司名/行业/地区过滤。实际搜索词：{keyword_text}。"
            )
        return (
            f"中国制造网本次未采集到可入库公司：候选企业 {self.last_candidate_count} 个，"
            f"实际搜索词：{keyword_text}。请换更具体的产品词或先完成页面登录验证。"
        )

    def create_browser_session(self, playwright) -> BrowserSession:
        context = self.launch_persistent_context(playwright)
        return BrowserSession(context=context)

    def build_launch_args(self) -> Dict:
        launch_args = {"headless": self.config.qcc_public_web_headless}
        if self.config.qcc_public_web_browser_channel:
            launch_args["channel"] = self.config.qcc_public_web_browser_channel
        return launch_args

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        user_data_dir = self.get_user_data_dir()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        context_args = {
            **self.build_launch_args(),
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        try:
            return playwright.chromium.launch_persistent_context(str(user_data_dir), **context_args)
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured browser channel is unavailable, fallback to bundled chromium")
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(str(user_data_dir), **context_args)

    def get_user_data_dir(self) -> Path:
        return self.config.qcc_public_web_user_data_dir.parent / "made-in-china"

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.get_user_data_dir())
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"中国制造网采集浏览器资料目录正在被占用，请先关闭预登录/采集浏览器。当前占用进程：{process_text}")

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self.clean_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"中国制造网采集浏览器启动失败：{message}"

    def search_candidate(self, page, keyword: str, collect_limit: int, industry: str) -> List[MadeInChinaCandidate]:
        if collect_limit <= 0 or not self.is_valid_search_keyword(industry, keyword):
            return []
        candidate_list: List[MadeInChinaCandidate] = []
        page_number = 1
        max_page_count = min(MADE_IN_CHINA_MAX_SEARCH_PAGE_COUNT, max(1, ((collect_limit + 9) // 10) + 1))
        while page_number <= max_page_count and len(candidate_list) < collect_limit * 2:
            page_start_count = len(candidate_list)
            logger.info("Made-in-China search start, keyword=%s, page=%s", keyword, page_number)
            self.goto_search_page(page, keyword, page_number)
            self.scroll_result_page_to_load(page)
            raw_item_list = self.extract_raw_item_list(page)
            self.last_raw_item_count += len(raw_item_list)
            for raw_item in raw_item_list:
                candidate = self.build_candidate(keyword, raw_item, industry)
                if candidate is not None:
                    candidate.search_url = page.url
                    candidate_list.append(candidate)
            candidate_list = self.dedupe_candidate_list(candidate_list)
            self.last_candidate_count = max(self.last_candidate_count, len(candidate_list))
            if len(candidate_list) == page_start_count and page_number >= 2:
                break
            page_number += 1
            self.wait_between_page()
        return self.dedupe_candidate_list(candidate_list)

    def goto_search_page(self, page, keyword: str, page_number: int) -> None:
        search_url = self.build_search_url(keyword, page_number)
        self.goto_public_page(page, search_url)
        self.activate_company_tab(page)
        self.apply_south_china_filter(page)

    def build_search_url(self, keyword: str, page_number: int) -> str:
        encoded_keyword = quote(quote(keyword, safe=""), safe="")
        page_query = f"&page={page_number}" if page_number > 1 else ""
        return (
            "https://cn.made-in-china.com/productdirectory.do"
            "?subaction=hunt&style=b&mode=and&code=0&order=0&newCn=1"
            f"&word={encoded_keyword}&comProvince=Guangdong{page_query}"
        )

    def build_search_keyword_list(self, industry: str, keywords: List[str]) -> List[str]:
        keyword_list = []
        raw_keyword_list = []
        for keyword in keywords:
            raw_keyword_list.extend(re.split(r"[,，、/\n\r]+", keyword or ""))
        if not raw_keyword_list:
            raw_keyword_list = INDUSTRY_PUBLIC_SEARCH_KEYWORD_MAP.get(industry, [industry])
        for raw_keyword in raw_keyword_list:
            keyword = self.clean_made_in_china_search_keyword(raw_keyword)
            if not self.is_valid_search_keyword(industry, keyword):
                continue
            if not self.build_keyword_business_token_list(keyword) and not self.is_company_name_keyword(keyword):
                keyword = f"{keyword}工厂"
            append_unique_text(keyword_list, keyword)
        if keyword_list:
            return keyword_list
        for raw_keyword in INDUSTRY_PUBLIC_SEARCH_KEYWORD_MAP.get(industry, [industry]):
            keyword = self.clean_made_in_china_search_keyword(raw_keyword)
            if self.is_valid_search_keyword(industry, keyword):
                append_unique_text(keyword_list, keyword)
        return keyword_list

    def clean_made_in_china_search_keyword(self, keyword: str) -> str:
        clean_keyword = self.clean_text(keyword)
        clean_keyword = re.sub(r"[\"'`“”‘’\[\]{}()（）<>《》]+", "", clean_keyword)
        clean_keyword = re.sub(r"\s+", "", clean_keyword)
        return clean_keyword.strip("，。;；、?|\\-_")

    def goto_public_page(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
            page.wait_for_timeout(1200)
        except PlaywrightTimeoutError:
            logger.warning("Made-in-China public page timeout, url=%s", url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("Made-in-China public page navigation interrupted, url=%s, error=%s", url, self.clean_text(str(ex))[:160])
            page.wait_for_timeout(1600)
        self.assert_public_page_allowed(page)

    def activate_company_tab(self, page) -> None:
        for text in ["公司信息", "公司", "供应商"]:
            try:
                locator = page.get_by_text(text, exact=True).first
                if locator.count() <= 0:
                    continue
                locator.click(timeout=2500)
                page.wait_for_timeout(1000)
                return
            except PlaywrightError:
                continue

    def apply_south_china_filter(self, page) -> None:
        try:
            for text in ["所有地区", "地区"]:
                locator = page.get_by_text(text, exact=True).first
                if locator.count() > 0:
                    locator.click(timeout=2500)
                    page.wait_for_timeout(500)
                    break
            for text in ["华南", "广东"]:
                locator = page.get_by_text(text, exact=True).first
                if locator.count() > 0:
                    locator.click(timeout=2500)
                    page.wait_for_timeout(1200)
                    return
        except PlaywrightError:
            logger.info("Made-in-China region filter click skipped")

    def assert_public_page_allowed(self, page) -> None:
        page_text = self.get_page_text(page)[:3000]
        if any(token in page_text for token in MADE_IN_CHINA_BLOCKED_TEXT_TOKEN_LIST):
            raise RuntimeError("中国制造网页面出现登录/验证码/访问限制，请先点击预登录中国制造网完成验证后再启动采集。")

    def extract_raw_item_list(self, page) -> List[Dict]:
        raw_item_list = []
        try:
            raw_item_list = page.evaluate(
                """
                () => {
                  const companyNamePattern = /[\\u4e00-\\u9fa5A-Za-z0-9（）()路\\-\\s]{2,80}?(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|商行|经营部|工作室|工厂|厂)/;
                  const skipTextTokenList = [
                    '中国制造网', 'Made-in-China', '首页', '产品信息', '采购信息', '热门产品',
                    '发布询价单', '在线交谈', '发联系信', '免费订阅', '登录', '注册'
                  ];
                  const normalizeText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                  const isVisible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                  };
                  const isCandidateHref = (href) => {
                    if (!href) {
                      return false;
                    }
                    let url;
                    try {
                      url = new URL(href, location.href);
                    } catch (error) {
                      return false;
                    }
                    const host = url.hostname.toLowerCase();
                    const path = url.pathname.toLowerCase();
                    if (!host.endsWith('made-in-china.com')) {
                      return false;
                    }
                    if (host.includes('membercenter') || host.includes('login') || path.includes('login')) {
                      return false;
                    }
                    return true;
                  };
                  const findCard = (element) => {
                    let current = element;
                    for (let depth = 0; current && depth < 8; depth += 1) {
                      const text = normalizeText(current.innerText || '');
                      const rect = current.getBoundingClientRect();
                      if (rect.width >= 280 && rect.height >= 50 && rect.height <= 680 && companyNamePattern.test(text)) {
                        return current;
                      }
                      current = current.parentElement;
                    }
                    return null;
                  };
                  const resultList = [];
                  const seenKeySet = new Set();
                  const companyCardList = Array.from(document.querySelectorAll('.co-item')).slice(0, 160);
                  for (const card of companyCardList) {
                    if (!isVisible(card)) {
                      continue;
                    }
                    const parentText = normalizeText(card.innerText || '');
                    const companyAnchor = card.querySelector('.co-name a[title], .co-hd .co-name a');
                    if (!companyAnchor || !isCandidateHref(companyAnchor.href || '')) {
                      continue;
                    }
                    const companyName = normalizeText(companyAnchor.getAttribute('title') || companyAnchor.innerText || '');
                    if (!companyName || companyName.length < 4 || skipTextTokenList.some((token) => companyName.includes(token))) {
                      continue;
                    }
                    const introTextList = Array.from(card.querySelectorAll('.co-intro a'))
                      .map((anchor) => normalizeText(anchor.getAttribute('title') || anchor.innerText || ''))
                      .filter((text) => text && text !== companyName && !/^\\d+\\s*/.test(text))
                      .slice(0, 6);
                    const seenKey = `${companyAnchor.href}|${companyName}`;
                    if (seenKeySet.has(seenKey)) {
                      continue;
                    }
                    seenKeySet.add(seenKey);
                    resultList.push({
                      href: new URL(companyAnchor.href, location.href).href,
                      text: introTextList.join(' '),
                      title: companyName,
                      companyName,
                      parentText: parentText.slice(0, 1600),
                      cardIndex: resultList.length
                    });
                    if (resultList.length >= 100) {
                      break;
                    }
                  }
                  if (resultList.length > 0) {
                    return resultList;
                  }
                  const productCardList = Array.from(document.querySelectorAll('li.prod-item, .prod-item')).slice(0, 160);
                  for (const card of productCardList) {
                    if (!isVisible(card)) {
                      continue;
                    }
                    const parentText = normalizeText(card.innerText || '');
                    const companyAnchor = Array.from(card.querySelectorAll('a.company-name-js, a.co-name'))
                      .find((anchor) => normalizeText(anchor.getAttribute('title') || anchor.innerText || '').length >= 4);
                    if (!companyAnchor || !isCandidateHref(companyAnchor.href || '')) {
                      continue;
                    }
                    const companyName = normalizeText(companyAnchor.getAttribute('title') || companyAnchor.innerText || '');
                    if (!companyName || companyName.length < 4 || skipTextTokenList.some((token) => companyName.includes(token))) {
                      continue;
                    }
                    const productAnchor = card.querySelector('a.pro-name, a[title]');
                    const text = normalizeText(productAnchor ? productAnchor.innerText : '');
                    const title = normalizeText(productAnchor ? (productAnchor.getAttribute('title') || '') : '');
                    const seenKey = `${companyAnchor.href}|${companyName}`;
                    if (seenKeySet.has(seenKey)) {
                      continue;
                    }
                    seenKeySet.add(seenKey);
                    resultList.push({
                      href: new URL(companyAnchor.href, location.href).href,
                      text,
                      title,
                      companyName,
                      parentText: parentText.slice(0, 1600),
                      cardIndex: resultList.length
                    });
                    if (resultList.length >= 100) {
                      break;
                    }
                  }
                  if (resultList.length > 0) {
                    return resultList;
                  }
                  for (const anchor of Array.from(document.querySelectorAll('a[href]')).slice(0, 2200)) {
                    if (!isVisible(anchor) || !isCandidateHref(anchor.href || '')) {
                      continue;
                    }
                    const card = findCard(anchor);
                    if (!card) {
                      continue;
                    }
                    const text = normalizeText(anchor.innerText || '');
                    const title = normalizeText(anchor.getAttribute('title') || '');
                    const parentText = normalizeText(card.innerText || '');
                    const mergedText = `${text} ${title} ${parentText}`;
                    if (!companyNamePattern.test(mergedText)) {
                      continue;
                    }
                    if (skipTextTokenList.some((token) => text === token || title === token || mergedText.startsWith(token))) {
                      continue;
                    }
                    const companyMatch = mergedText.match(companyNamePattern);
                    const companyName = companyMatch ? companyMatch[0].replace(/\\s+/g, '') : '';
                    const seenKey = `${anchor.href}|${companyName}`;
                    if (seenKeySet.has(seenKey)) {
                      continue;
                    }
                    seenKeySet.add(seenKey);
                    resultList.push({
                      href: new URL(anchor.href, location.href).href,
                      text,
                      title,
                      parentText: parentText.slice(0, 1600),
                      cardIndex: resultList.length
                    });
                    if (resultList.length >= 100) {
                      break;
                    }
                  }
                  return resultList;
                }
                """
            )
        except PlaywrightError:
            logger.warning("Made-in-China raw item extraction failed")
        if raw_item_list:
            return raw_item_list
        return self.extract_raw_item_list_from_text(page)

    def extract_raw_item_list_from_text(self, page) -> List[Dict]:
        page_text = self.clean_text(self.get_page_text(page))
        result_list = []
        seen_company_name_set = set()
        for match in COMPANY_NAME_PATTERN.finditer(page_text):
            company_name = clean_company_name_text(match.group(1))
            if not self.is_valid_company_name(company_name):
                continue
            if company_name in seen_company_name_set:
                continue
            seen_company_name_set.add(company_name)
            start_index = max(0, match.start() - 120)
            end_index = min(len(page_text), match.end() + 500)
            chunk = page_text[start_index:end_index]
            result_list.append(
                {
                    "href": page.url,
                    "text": company_name,
                    "title": "",
                    "parentText": chunk,
                    "cardIndex": len(result_list),
                }
            )
            if len(result_list) >= 100:
                break
        return result_list

    def build_candidate(self, keyword: str, raw_item: Dict, industry: str) -> Optional[MadeInChinaCandidate]:
        href = self.normalize_url(raw_item.get("href", ""))
        text = self.clean_text(raw_item.get("text", ""))
        title = self.clean_text(raw_item.get("title", ""))
        parent_text = self.clean_text(raw_item.get("parentText", ""))
        card_index = self.parse_int(raw_item.get("cardIndex", -1), -1)
        merged_text = " ".join([text, title, parent_text])
        if not merged_text:
            return None
        if text in MADE_IN_CHINA_SKIP_TEXT_TOKEN_LIST or title in MADE_IN_CHINA_SKIP_TEXT_TOKEN_LIST:
            return None
        preferred_company_name = self.extract_company_name(str(raw_item.get("companyName", "")))
        company_name = preferred_company_name or self.extract_company_name(merged_text)
        if not company_name:
            return None
        if href and not self.is_made_in_china_profile_url(href):
            href = ""
        if not self.is_search_result_card_relevant(keyword, industry, merged_text):
            return None
        product_name = self.extract_product_name(text, title, keyword, company_name)
        region_text = self.extract_region_text(merged_text)
        return MadeInChinaCandidate(
            source_keyword=keyword,
            company_name=company_name,
            product_name=product_name,
            profile_url=href,
            region_text=region_text,
            raw_text=merged_text,
            card_index=card_index,
        )

    def build_lead_from_candidate(self, candidate: MadeInChinaCandidate, industry: str) -> Optional[CollectedLeadDTO]:
        if candidate is None or not candidate.company_name:
            return None
        return CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword=candidate.source_keyword,
            industry=industry,
            suspected_company_name=candidate.company_name,
            product_name=candidate.product_name,
            contact_name="",
            phone="",
            phone_source="",
            website_url="",
            shop_url="",
            profile_url=candidate.profile_url,
            region_text=(candidate.region_text or candidate.raw_text)[:3000],
            is_enterprise_verified=True,
            commercial_keyword_count=self.count_business_keyword(candidate.raw_text),
        )

    def extract_company_name(self, text: str) -> str:
        for match in COMPANY_NAME_PATTERN.finditer(text):
            company_name = clean_company_name_text(match.group(1))
            if self.is_valid_company_name(company_name):
                return company_name
        return ""

    def is_valid_company_name(self, company_name: str) -> bool:
        clean_name = clean_company_name_text(company_name)
        if not super().is_valid_company_name(clean_name):
            return False
        if has_any_token(clean_name, MADE_IN_CHINA_SKIP_TEXT_TOKEN_LIST):
            return False
        if KEYWORD_ONLY_COMPANY_PATTERN.match(clean_name):
            return False
        if re.match(r"^\d+\s*条", clean_name):
            return False
        if has_any_token(clean_name, ["哪里", "怎么找", "格局", "市场观察", "为什么大家"]):
            return False
        return clean_name.endswith(REAL_COMPANY_STRONG_SUFFIX_TUPLE)

    def is_made_in_china_profile_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        parsed_url = urlparse(url)
        host = parsed_url.netloc.lower()
        path = parsed_url.path.lower()
        if not host.endswith("made-in-china.com"):
            return False
        if host.startswith(("login.", "passport.")) or "membercenter" in host:
            return False
        if any(token in path for token in ("login", "signin", "member", "cart", "inquiry", "message")):
            return False
        if any(token in path for token in ("productdirectory", "companysearch", "products", "productsearch")):
            return False
        if "/showroom/" in path or "-companyinfo" in path:
            return True
        return host != "cn.made-in-china.com"

    def extract_region_text(self, text: str) -> str:
        clean_text = self.clean_text(text)
        for pattern in [
            r"(广东省?[\u4e00-\u9fa5]{1,12}市[\u4e00-\u9fa5]{0,12}(?:区|县|镇|街道)?)",
            r"((?:广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|江门|肇庆|揭阳|潮州|湛江|茂名|阳江|清远|韶关|梅州|河源|汕尾|云浮)[市]?(?:[\u4e00-\u9fa5]{0,12}(?:区|县|镇|街道))?)",
        ]:
            match = re.search(pattern, clean_text)
            if match:
                return match.group(1).strip()
        if "华南" in clean_text or "广东" in clean_text:
            return "中国制造网华南/广东筛选"
        return ""

    def wait_between_page(self) -> None:
        sleep_with_jitter(self.config.qcc_public_web_request_interval_seconds, 0.35, 3.0)

    def wait_after_collected_lead(self, collected_count: int, collect_limit: int) -> None:
        if collected_count < collect_limit:
            self.wait_between_page()


class Alibaba1688PageAssistantCollector(Alibaba1688PublicPageCollector):
    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        keyword = self.pick_first_keyword(keywords)
        with sync_playwright() as playwright:
            browser_session = self.create_browser_session(playwright)
            context = browser_session.context
            page = context.new_page()
            try:
                self.goto_page_assistant_start_page(page, keyword)
                page.bring_to_front()
                page.wait_for_timeout(self.config.alibaba_1688_page_assistant_wait_seconds * 1000)
                self.assert_public_page_allowed(page)
                return self.extract_current_page_lead_list(page, industry, keyword, collect_limit)
            finally:
                context.close()
                if browser_session.browser is not None:
                    browser_session.browser.close()

    def pick_first_keyword(self, keywords: List[str]) -> str:
        for keyword in keywords:
            clean_keyword = keyword.strip()
            if clean_keyword:
                return clean_keyword
        return ""

    def goto_page_assistant_start_page(self, page, keyword: str) -> None:
        start_url = "https://www.1688.com/"
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=self.config.alibaba_1688_page_timeout_ms)
        except PlaywrightTimeoutError:
            logger.warning("1688 page assistant start page timeout, url=%s", start_url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning(
                "1688 page assistant start page navigation interrupted, url=%s, error=%s",
                start_url,
                self.clean_text(str(ex))[:160],
            )

    def extract_current_page_lead_list(
        self,
        page,
        industry: str,
        keyword: str,
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        raw_item_list = self.extract_raw_item_list(page)
        candidate_list = []
        for raw_item in raw_item_list:
            candidate = self.build_candidate(keyword, raw_item, industry)
            if candidate is not None:
                candidate_list.append(candidate)
        candidate_list = self.dedupe_candidate_list(candidate_list)
        if not candidate_list:
            candidate_list = self.extract_candidate_list_from_visible_text(page, keyword)

        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        for candidate in candidate_list:
            if len(result_list) >= collect_limit:
                break
            lead = self.build_lead_from_candidate_text(
                candidate,
                industry,
                SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT,
            )
            if lead is None:
                continue
            dedupe_key = self.build_dedupe_key(lead)
            if dedupe_key in dedupe_key_set:
                continue
            dedupe_key_set.add(dedupe_key)
            result_list.append(lead)
        return result_list

    def extract_candidate_list_from_visible_text(self, page, keyword: str) -> List[AlibabaCandidate]:
        page_text = self.clean_text(self.get_page_text(page))
        candidate_list = []
        for match in COMPANY_NAME_PATTERN.finditer(page_text):
            company_name = self.remove_inner_space(match.group(1))
            if not self.is_valid_company_name(company_name):
                continue
            chunk = page_text[match.start() : match.start() + 500]
            candidate_list.append(
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name=company_name,
                    product_name=self.extract_product_name(chunk[:120], "", keyword, company_name),
                    shop_url="",
                    profile_url=page.url,
                    raw_text=chunk,
                )
            )
        return self.dedupe_candidate_list(candidate_list)


class Alibaba1688SnapshotParser(Alibaba1688PublicPageCollector):
    def parse_snapshot(
        self,
        industry: str,
        source_keyword: str,
        page_url: str,
        page_title: str,
        page_text: str,
        card_list: List[Dict],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        keyword = self.pick_snapshot_keyword(industry, source_keyword, page_title)
        detail_candidate = self.build_detail_page_candidate(keyword, page_url, page_title, page_text)
        candidate_list = [detail_candidate] if detail_candidate is not None else []
        if not candidate_list:
            candidate_list = self.build_candidate_list_from_card(keyword, page_url, card_list)
        if not candidate_list:
            candidate_list = self.build_candidate_list_from_page_text(keyword, page_url, page_text)

        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        for candidate in candidate_list:
            if len(result_list) >= collect_limit:
                break
            lead = self.build_lead_from_candidate_text(
                candidate,
                industry,
                SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
            )
            if lead is None:
                continue
            dedupe_key = self.build_dedupe_key(lead)
            if dedupe_key in dedupe_key_set:
                continue
            dedupe_key_set.add(dedupe_key)
            result_list.append(lead)
        return result_list

    def pick_snapshot_keyword(self, industry: str, source_keyword: str, page_title: str) -> str:
        for value in [source_keyword, self.extract_keyword_from_text(page_title), industry]:
            keyword = self.clean_product_text(value, "")
            if keyword and not self.contains_mojibake(keyword):
                return keyword[:40]
        return "1688当前页面"

    def build_detail_page_candidate(
        self,
        keyword: str,
        page_url: str,
        page_title: str,
        page_text: str,
    ) -> Optional[AlibabaCandidate]:
        clean_page_text = self.clean_text(page_text)
        if not clean_page_text or not any(token in clean_page_text for token in DETAIL_PAGE_TOKEN_LIST):
            return None
        company_name = self.extract_company_name(clean_page_text)
        if not company_name:
            return None
        product_name = (
            self.extract_main_product_text(clean_page_text)
            or self.extract_product_name(page_title, clean_page_text[:180], keyword, company_name)
        )
        return AlibabaCandidate(
            source_keyword=keyword,
            company_name=company_name,
            product_name=product_name,
            shop_url=self.pick_shop_url(page_url) if self.is_valid_1688_url(page_url) else "",
            profile_url=page_url,
            raw_text=clean_page_text[:20000],
        )

    def extract_main_product_text(self, text: str) -> str:
        match = re.search(r"主营[:：]\s*([^。；;\n]{2,120})", text)
        if not match:
            return ""
        value = match.group(1)
        value = re.split(
            r"([\u4e00-\u9fa5]{2,4}\s*(?:厂长|经理|负责人)|来样加工|来图加工|加工方式|支持外贸订单|"
            r"CCC认证|ISO|AA诚信|地址|地图查看|关注|联系人|联系电话|电话来源|电话联系|立即询价|"
            r"负责工厂|业务联系人|厂长|经理|负责人)",
            value,
        )[0]
        value = self.clean_product_text(value, "")
        return value[:80]

    def build_candidate_list_from_card(
        self,
        keyword: str,
        page_url: str,
        card_list: List[Dict],
    ) -> List[AlibabaCandidate]:
        candidate_list: List[AlibabaCandidate] = []
        for card in card_list:
            raw_text = self.clean_text(card.get("text", ""))
            if not raw_text:
                continue
            company_name = self.extract_company_name(raw_text)
            if not company_name or not self.looks_like_company_card(raw_text, company_name):
                continue
            href = self.normalize_url(card.get("href", ""))
            profile_url = href if self.is_valid_1688_url(href) else page_url
            candidate_list.append(
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name=company_name,
                    product_name=self.extract_product_name(raw_text[:140], "", keyword, company_name),
                    shop_url=self.pick_shop_url(profile_url) if self.is_valid_1688_url(profile_url) else "",
                    profile_url=profile_url,
                    raw_text=raw_text,
                )
            )
        return self.dedupe_candidate_list(candidate_list)

    def looks_like_company_card(self, raw_text: str, company_name: str) -> bool:
        if not self.is_valid_company_name(company_name):
            return False
        if any(token in raw_text for token in ["响应率", "回头率", "履约率", "诚信", "来样加工", "来图加工", "加工", "批发"]):
            return True
        return any(token in company_name for token in ["有限公司", "商行", "经营部", "工厂"])

    def build_candidate_list_from_page_text(
        self,
        keyword: str,
        page_url: str,
        page_text: str,
    ) -> List[AlibabaCandidate]:
        clean_page_text = self.clean_text(page_text)
        candidate_list: List[AlibabaCandidate] = []
        for match in COMPANY_NAME_PATTERN.finditer(clean_page_text):
            company_name = self.remove_inner_space(match.group(1))
            if not self.is_valid_company_name(company_name):
                continue
            chunk = clean_page_text[match.start() : match.start() + 600]
            candidate_list.append(
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name=company_name,
                    product_name=self.extract_product_name(chunk[:140], "", keyword, company_name),
                    shop_url="",
                    profile_url=page_url,
                    raw_text=chunk,
                )
            )
        return self.dedupe_candidate_list(candidate_list)

    def extract_keyword_from_text(self, text: str) -> str:
        clean_text = self.clean_text(text)
        if not clean_text:
            return ""
        return clean_text.split("-")[0].split("_")[0].strip()[:40]


class QichachaPublicWebCollector:
    UNPUBLISHED_PHONE_TEXT = "号码皆未公开"
    MAX_RELATED_COMPANY_CHECK_COUNT = 100
    COMPANY_PATTERN = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,80}"
        r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|厂|商行|经营部|工作室))"
    )
    INVALID_COMPANY_TOKEN_LIST = ["企查查", "登录", "注册", "搜索", "风险", "验证码"]
    BLOCKED_URL_TOKEN_LIST = ["login.qcc.com", "user.qcc.com/login", "passport.qcc.com", "/405.html"]
    BLOCKED_TEXT_TOKEN_LIST = [
        "请完成验证",
        "安全验证",
        "拖动下方滑块",
        "请输入验证码",
        "访问被拒绝",
        "访问过于频繁",
        "访问被阻断",
        "安全威胁",
        "为了您的账号安全",
        "当前操作存在风险",
    ]
    BUSINESS_KEYWORD_LIST = ["工厂", "批发", "供应链", "生产", "制造", "OEM", "ODM", "加工", "进出口", "跨境"]

    def __init__(self):
        self.config = get_config()

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        clean_keyword_list = build_guangdong_first_keyword_list(keywords, industry)
        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()

        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            page = context.new_page()
            try:
                for keyword in clean_keyword_list:
                    if len(result_list) >= collect_limit:
                        break
                    self.goto_search_page(page, keyword)
                    candidate_list = self.extract_candidate_list(page, keyword, industry)
                    for lead in candidate_list:
                        if len(result_list) >= collect_limit:
                            break
                        lead = self.enrich_lead_from_detail_and_related(page, lead)
                        if not is_active_public_company_lead(lead):
                            continue
                        if not self.is_guangdong_lead(lead):
                            continue
                        if not is_industry_relevant_public_lead(lead):
                            continue
                        if not has_public_phone_text(lead.phone):
                            continue
                        dedupe_key = self.build_dedupe_key(lead)
                        if dedupe_key in dedupe_key_set:
                            continue
                        dedupe_key_set.add(dedupe_key)
                        result_list.append(lead)
                    self.wait_between_page()
            finally:
                context.close()
        return result_list

    def collect_by_company_names(
        self,
        industry: str,
        company_name_list: List[str],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        clean_company_name_list = []
        for company_name in company_name_list:
            clean_company_name = self.clean_text(company_name)
            if not clean_company_name or clean_company_name in clean_company_name_list:
                continue
            clean_company_name_list.append(clean_company_name)

        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            page = context.new_page()
            try:
                for company_name in clean_company_name_list:
                    if len(result_list) >= collect_limit:
                        break
                    self.goto_search_page(page, company_name)
                    candidate_list = self.extract_candidate_list(page, company_name, industry)
                    lead = self.pick_best_company_match(company_name, candidate_list)
                    if lead is None:
                        continue
                    lead = self.enrich_lead_from_detail_and_related(page, lead)
                    lead.source_keyword = company_name
                    lead.source_type = SOURCE_TYPE_QCC_PUBLIC_WEB
                    if not is_active_public_company_lead(lead):
                        continue
                    if not is_industry_relevant_public_lead(lead):
                        continue
                    dedupe_key = self.build_dedupe_key(lead)
                    if dedupe_key in dedupe_key_set:
                        continue
                    dedupe_key_set.add(dedupe_key)
                    result_list.append(lead)
                    self.wait_between_page()
            finally:
                context.close()
        return result_list

    def pick_best_company_match(
        self,
        company_name: str,
        candidate_list: List[CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        if not candidate_list:
            return None
        clean_company_name = self.clean_text(company_name)
        for lead in candidate_list:
            if self.clean_text(lead.suspected_company_name) == clean_company_name:
                return lead
        for lead in candidate_list:
            candidate_name = self.clean_text(lead.suspected_company_name)
            if clean_company_name in candidate_name or candidate_name in clean_company_name:
                return lead
        return candidate_list[0]

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        context_args = {
            "headless": self.config.qcc_public_web_headless,
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        if self.config.qcc_public_web_browser_channel:
            context_args["channel"] = self.config.qcc_public_web_browser_channel
        try:
            return playwright.chromium.launch_persistent_context(
                str(self.config.qcc_public_web_user_data_dir),
                **context_args,
            )
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured QCC browser channel is unavailable, fallback to bundled chromium")
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(
                str(self.config.qcc_public_web_user_data_dir),
                **context_args,
            )

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.config.qcc_public_web_user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"企查查采集专用浏览器资料目录正在被占用，请先关闭预热/采集浏览器后再启动任务。当前占用进程：{process_text}")

    def goto_search_page(self, page, keyword: str) -> None:
        search_url = f"https://www.qcc.com/web/search?key={quote_plus(keyword)}"
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
            page.wait_for_timeout(1800)
        except PlaywrightTimeoutError:
            logger.warning("QCC public search page timeout, url=%s", search_url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("QCC public search navigation interrupted, url=%s, error=%s", search_url, self.clean_text(str(ex))[:160])
            page.wait_for_timeout(1600)
        self.assert_public_page_allowed(page)

    def assert_public_page_allowed(self, page) -> None:
        blocked_reason = self.get_blocked_reason(page)
        if not blocked_reason:
            return
        if self.config.qcc_public_web_manual_verify_enabled:
            self.wait_for_manual_recovery(page, blocked_reason)
            return
        raise RuntimeError(f"{blocked_reason}，已停止采集")

    def get_blocked_reason(self, page) -> str:
        page_url = page.url.lower()
        page_text = self.get_page_text(page)[:4000]
        if "/405.html" in page_url:
            return "企查查公开页面出现405访问阻断"
        if any(token in page_url for token in self.BLOCKED_URL_TOKEN_LIST):
            return "企查查公开页面跳转到登录页"
        if any(token in page_text for token in self.BLOCKED_TEXT_TOKEN_LIST):
            return "企查查公开页面出现登录/验证/风控要求"
        return ""

    def wait_for_manual_recovery(self, page, blocked_reason: str) -> None:
        logger.warning("%s，等待人工完成验证或登录", blocked_reason)
        try:
            page.bring_to_front()
        except PlaywrightError:
            logger.warning("Could not bring QCC page to front")

        start_time = time.monotonic()
        timeout_seconds = self.config.qcc_public_web_manual_verify_timeout_seconds
        poll_seconds = self.config.qcc_public_web_manual_verify_poll_seconds
        while time.monotonic() - start_time <= timeout_seconds:
            page.wait_for_timeout(int(poll_seconds * 1000))
            if not self.get_blocked_reason(page):
                logger.info("企查查页面已人工恢复，继续采集公开页面")
                return
        raise RuntimeError(f"{blocked_reason}，人工验证等待超时，已停止采集")

    def extract_candidate_list(self, page, keyword: str, industry: str) -> List[CollectedLeadDTO]:
        self.expand_more_phone_buttons(page)
        raw_item_list = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/firm/"], a[href*="/web/firm/"]')).slice(0, 800).map((element) => {
              const card = element.closest(
                'tr, li, section, div[class*="search"], div[class*="result"], div[class*="item"], div[class*="card"]'
              );
              const parent = card || element.parentElement;
              return {
                href: element.href || '',
                text: (element.innerText || '').trim(),
                title: (element.getAttribute('title') || '').trim(),
                parentText: ((parent && parent.innerText) || '').trim().slice(0, 1800)
              };
            })
            """
        )
        lead_list: List[CollectedLeadDTO] = []
        for raw_item in raw_item_list:
            lead = self.build_lead(keyword, industry, raw_item)
            if lead is not None:
                lead_list.append(lead)
        if lead_list:
            return self.dedupe_lead_list(lead_list)
        return []

    def expand_more_phone_buttons(self, page) -> None:
        try:
            expand_count = page.evaluate(
                """
                () => {
                  const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && rect.width > 0
                      && rect.height > 0;
                  };
                  const elements = Array.from(document.querySelectorAll('button, a, span'))
                    .filter((element) => {
                      const text = (element.innerText || '').trim();
                      return isVisible(element) && text.length <= 12 && /更多\\s*\\d*/.test(text);
                    })
                    .slice(0, 20);
                  elements.forEach((element) => element.click());
                  return elements.length;
                }
                """
            )
            if expand_count > 0:
                page.wait_for_timeout(900)
                self.assert_public_page_allowed(page)
        except PlaywrightError:
            logger.warning("QCC phone expand click failed, continue with visible fields")

    def enrich_lead_from_detail_and_related(self, page, lead: CollectedLeadDTO) -> CollectedLeadDTO:
        phone_list = self.split_phone_text(lead.phone)
        related_checked_count = 0
        legal_person = ""

        if self.is_valid_qcc_url(lead.profile_url):
            try:
                self.goto_public_url(page, lead.profile_url)
                self.expand_more_phone_buttons(page)
                detail_text = self.clean_text(self.get_page_text(page))
                phone_list.extend(self.split_phone_text(self.extract_phone(detail_text)))
                detail_contact_name = self.extract_contact_name(detail_text)
                legal_person = self.extract_legal_person(detail_text)
                lead.contact_name = lead.contact_name or detail_contact_name or legal_person or lead.legal_person
                lead.legal_person = legal_person or lead.legal_person
                lead.company_status = self.extract_company_status(detail_text) or lead.company_status
                lead.unified_social_credit_code = (
                    extract_credit_code_from_text(detail_text) or lead.unified_social_credit_code
                )
                lead.business_scope = self.extract_business_scope(detail_text) or lead.business_scope
                lead.registered_address = self.extract_registered_address(detail_text) or lead.registered_address
                lead.region_text = " ".join([lead.region_text, detail_text[:3000]])
                lead.product_name = self.extract_product_name(detail_text, lead.source_keyword, lead.industry)
            except PlaywrightError:
                logger.warning("QCC detail page enrich failed, company=%s", lead.suspected_company_name)

        if not phone_list and legal_person:
            related_company_list = self.extract_related_company_list_from_legal_person(page, legal_person, lead)
            for related_company in related_company_list[: self.MAX_RELATED_COMPANY_CHECK_COUNT]:
                if related_company["company_name"] == lead.suspected_company_name:
                    continue
                related_checked_count += 1
                related_phone_list = self.extract_phone_list_from_related_company(page, related_company)
                phone_list.extend(related_phone_list)

        phone_list = self.dedupe_text_list(phone_list)
        if phone_list:
            lead.phone = "；".join(phone_list)
            if related_checked_count > 0:
                lead.phone_source = "企查查公开页 + 法人关联企业公开页"
            else:
                lead.phone_source = "企查查公开页可见字段（含已展开更多）"
            return lead

        lead.phone = self.UNPUBLISHED_PHONE_TEXT
        lead.phone_source = "当前企业及法人关联企业公开页均未展示电话"
        return lead

    def goto_public_url(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
            page.wait_for_timeout(1400)
        except PlaywrightTimeoutError:
            logger.warning("QCC public detail page timeout, url=%s", url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("QCC public detail navigation interrupted, url=%s, error=%s", url, self.clean_text(str(ex))[:160])
            page.wait_for_timeout(1400)
        self.assert_public_page_allowed(page)

    def extract_related_company_list_from_legal_person(
        self,
        page,
        legal_person: str,
        lead: CollectedLeadDTO,
    ) -> List[Dict]:
        self.open_legal_person_related_area(page, legal_person)
        raw_related_list = self.extract_company_link_list(page)
        result_list = []
        dedupe_key_set = set()
        for item in raw_related_list:
            company_name = self.extract_company_name(item.get("text", ""))
            href = self.normalize_url(item.get("href", ""))
            if not company_name or not self.is_valid_qcc_url(href):
                continue
            if company_name == lead.suspected_company_name:
                continue
            dedupe_key = company_name or href
            if dedupe_key in dedupe_key_set:
                continue
            dedupe_key_set.add(dedupe_key)
            result_list.append({"company_name": company_name, "href": href})
        return result_list

    def open_legal_person_related_area(self, page, legal_person: str) -> None:
        if not legal_person:
            return
        try:
            clicked = page.evaluate(
                """
                (legalPerson) => {
                  const candidates = Array.from(document.querySelectorAll('a, button, span, div'));
                  const legalPersonElement = candidates.find((element) => {
                    const text = (element.innerText || '').trim();
                    return text.includes(legalPerson) && text.length <= legalPerson.length + 20;
                  });
                  if (legalPersonElement) {
                    const scope = legalPersonElement.closest('tr, li, section, div[class*="card"], div[class*="item"]')
                      || legalPersonElement.parentElement
                      || document.body;
                    const relatedEntry = Array.from(scope.querySelectorAll('a, button, span'))
                      .find((element) => /关联企业|对外投资|任职|全部|更多/.test((element.innerText || '').trim()));
                    if (relatedEntry) {
                      relatedEntry.click();
                      return true;
                    }
                  }
                  const fallback = candidates.find((element) => {
                    const text = (element.innerText || '').trim();
                    return text === legalPerson;
                  });
                  if (fallback) {
                    fallback.click();
                    return true;
                  }
                  return false;
                }
                """,
                legal_person,
            )
            if not clicked:
                return
            page.wait_for_timeout(1200)
            self.assert_public_page_allowed(page)
        except PlaywrightError:
            logger.warning("QCC legal person related area not opened, legal_person=%s", legal_person)

    def extract_company_link_list(self, page) -> List[Dict]:
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href]')).slice(0, 1000).map((element) => {
              const row = element.closest('tr, li, div[class*="table"], div[class*="modal"], div[class*="item"]');
              const parent = row || element.parentElement;
              return {
                href: element.href || '',
                text: [
                  (element.innerText || '').trim(),
                  ((parent && parent.innerText) || '').trim()
                ].join(' ').slice(0, 1200)
              };
            })
            """
        )

    def extract_phone_list_from_related_company(self, page, related_company: Dict) -> List[str]:
        try:
            self.goto_public_url(page, related_company["href"])
            self.expand_more_phone_buttons(page)
            page_text = self.clean_text(self.get_page_text(page))
            return self.split_phone_text(self.extract_phone(page_text))
        except PlaywrightError:
            logger.warning("QCC related company phone extract failed, company=%s", related_company.get("company_name", ""))
            return []

    def build_lead(self, keyword: str, industry: str, raw_item: Dict) -> Optional[CollectedLeadDTO]:
        href = self.normalize_url(raw_item.get("href", ""))
        if not self.is_valid_qcc_url(href):
            return None
        merged_text = self.clean_text(
            " ".join(
                [
                    raw_item.get("text", ""),
                    raw_item.get("title", ""),
                    raw_item.get("parentText", ""),
                ]
            )
        )
        company_name = clean_company_name_text(self.extract_company_name(merged_text))
        if not company_name:
            return None
        phone = self.extract_phone(merged_text)
        return CollectedLeadDTO(
            source_type=SOURCE_TYPE_QCC_PUBLIC_WEB,
            source_keyword=keyword,
            industry=industry,
            suspected_company_name=company_name,
            product_name=self.extract_product_name(merged_text, keyword, industry),
            contact_name=self.extract_contact_name(merged_text),
            phone=phone,
            phone_source="企查查公开页可见字段（含已展开更多）" if phone else "",
            legal_person=self.extract_legal_person(merged_text),
            company_status=self.extract_company_status(merged_text),
            unified_social_credit_code=extract_credit_code_from_text(merged_text),
            business_scope=self.extract_business_scope(merged_text),
            registered_address=self.extract_registered_address(merged_text),
            region_text=merged_text[:3000],
            profile_url=href,
            is_enterprise_verified=True,
            commercial_keyword_count=self.count_business_keyword(merged_text),
        )

    def extract_candidate_list_from_visible_text(
        self,
        page,
        keyword: str,
        industry: str,
    ) -> List[CollectedLeadDTO]:
        page_text = self.clean_text(self.get_page_text(page))
        lead_list: List[CollectedLeadDTO] = []
        for match in self.COMPANY_PATTERN.finditer(page_text):
            company_name = clean_company_name_text(match.group(1))
            if not self.is_valid_company_name(company_name):
                continue
            chunk = page_text[match.start() : match.start() + 900]
            phone = self.extract_phone(chunk)
            lead_list.append(
                CollectedLeadDTO(
                    source_type=SOURCE_TYPE_QCC_PUBLIC_WEB,
                    source_keyword=keyword,
                    industry=industry,
                    suspected_company_name=company_name,
                    product_name=self.extract_product_name(chunk, keyword, industry),
                    contact_name=self.extract_contact_name(chunk),
                    phone=phone,
                    phone_source="企查查公开页可见字段（含已展开更多）" if phone else "",
                    legal_person=self.extract_legal_person(chunk),
                    company_status=self.extract_company_status(chunk),
                    unified_social_credit_code=extract_credit_code_from_text(chunk),
                    business_scope=self.extract_business_scope(chunk),
                    registered_address=self.extract_registered_address(chunk),
                    region_text=chunk[:3000],
                    profile_url=page.url,
                    is_enterprise_verified=True,
                    commercial_keyword_count=self.count_business_keyword(chunk),
                )
            )
        return self.dedupe_lead_list(lead_list)

    def extract_company_name(self, text: str) -> str:
        for match in self.COMPANY_PATTERN.finditer(text):
            company_name = clean_company_name_text(match.group(1))
            if self.is_valid_company_name(company_name):
                return company_name
        return ""

    def is_valid_company_name(self, company_name: str) -> bool:
        return is_valid_enterprise_name(company_name, self.INVALID_COMPANY_TOKEN_LIST)

    def extract_product_name(self, text: str, keyword: str, industry: str) -> str:
        scope_match = re.search(r"经营范围[:：\s]*([^。；;\n]{2,120})", text)
        if scope_match:
            return self.clean_text(scope_match.group(1))[:80]
        labeled_text = extract_public_labeled_business_text(text)
        for token in INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry]):
            if token and token in labeled_text:
                return token
        return ""

    def extract_phone(self, text: str) -> str:
        return clean_public_phone_text(text, include_service=False)

    def split_phone_text(self, phone_text: str) -> List[str]:
        return split_public_phone_text(phone_text, include_service=False)

    def extract_contact_name(self, text: str) -> str:
        return extract_contact_name_by_pattern(text)

    def extract_legal_person(self, text: str) -> str:
        match = re.search(r"(?:法定代表人|经营者|投资人)[:：\s]*([\u4e00-\u9fa5A-Za-z]{2,12})", text)
        if match:
            return match.group(1).strip()
        return ""

    def extract_company_status(self, text: str) -> str:
        return extract_public_company_status_text(text)

    def extract_business_scope(self, text: str) -> str:
        match = re.search(r"经营范围[:：\s]*([^。；;\n]{2,260})", text)
        if match:
            return self.clean_text(match.group(1))[:260]
        return ""

    def extract_registered_address(self, text: str) -> str:
        for label in ["注册地址", "经营场所", "住所", "地址"]:
            index = text.find(label)
            if index < 0:
                continue
            value = text[index + len(label): index + len(label) + 160]
            value = re.sub(r"^[：:\s]+", "", value)
            value = re.split(
                r"(?=法定代表人|经营者|投资人|注册资本|成立日期|登记状态|经营状态|统一社会信用代码|经营范围|电话|邮箱|风险)",
                value,
            )[0]
            value = value.strip(" ：:，,；;。")
            if value:
                return value
        guangdong_match = re.search(r"(广东省?[\u4e00-\u9fa5A-Za-z0-9（）()·\-号栋室层街路镇区县市]{6,120})", text)
        if guangdong_match:
            return guangdong_match.group(1).strip()
        return ""

    def count_business_keyword(self, text: str) -> int:
        return sum(1 for keyword in self.BUSINESS_KEYWORD_LIST if keyword in text)

    def is_guangdong_lead(self, lead: CollectedLeadDTO) -> bool:
        return is_reliable_guangdong_public_lead(lead)

    def get_page_text(self, page) -> str:
        try:
            return page.locator("body").inner_text(timeout=5000)
        except PlaywrightError:
            return ""

    def normalize_url(self, url: str) -> str:
        clean_url = url.strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        return clean_url

    def is_valid_qcc_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        parsed_url = urlparse(url)
        host = parsed_url.netloc.lower()
        path = parsed_url.path.lower()
        return host.endswith("qcc.com") and "login" not in host and "/firm/" in path and path.endswith(".html")

    def is_browser_channel_unavailable(self, ex: PlaywrightError) -> bool:
        message = str(ex).lower()
        return "executable doesn't exist" in message or "not found" in message

    def is_recoverable_navigation_error(self, ex: PlaywrightError) -> bool:
        message = str(ex)
        return "net::ERR_ABORTED" in message or "frame was detached" in message

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self.clean_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"企查查公开页采集浏览器启动失败：{message}"

    def clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def build_dedupe_key(self, lead: CollectedLeadDTO) -> str:
        return lead.suspected_company_name or lead.profile_url

    def dedupe_lead_list(self, lead_list: List[CollectedLeadDTO]) -> List[CollectedLeadDTO]:
        result_list = []
        dedupe_key_set = set()
        for lead in lead_list:
            dedupe_key = self.build_dedupe_key(lead)
            if not dedupe_key or dedupe_key in dedupe_key_set:
                continue
            dedupe_key_set.add(dedupe_key)
            result_list.append(lead)
        return result_list

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result_list = []
        dedupe_set = set()
        for text in text_list:
            clean_text = text.strip()
            if not clean_text or clean_text in dedupe_set:
                continue
            dedupe_set.add(clean_text)
            result_list.append(clean_text)
        return result_list

    def wait_between_page(self) -> None:
        sleep_with_jitter(self.config.qcc_public_web_request_interval_seconds, 0.35, 3.0)


class FengniaoPublicWebCollector:
    COMPANY_PATTERN = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,80}"
        r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|厂|商行|经营部|工作室))"
    )
    INVALID_COMPANY_TOKEN_LIST = ["风鸟", "美亚", "登录", "注册", "搜索", "验证码"]
    BLOCKED_URL_TOKEN_LIST = ["login", "passport"]
    BLOCKED_TEXT_TOKEN_LIST = [
        "请完成验证",
        "安全验证",
        "拖动滑块",
        "验证码",
        "验证码登录/注册",
        "扫码注册/登录",
        "请输入手机号",
        "请输入图片验证码",
        "请输入短信验证码",
        "获取验证码",
        "密码登录",
        "登录即表示同意",
        "注册即送",
        "免费查询额度",
        "用户协议",
        "隐私政策",
        "访问过于频繁",
        "今日查询额度已用完",
        "请登录",
    ]
    BUSINESS_KEYWORD_LIST = ["工厂", "批发", "供应链", "生产", "制造", "OEM", "ODM", "加工", "进出口", "跨境"]

    def __init__(self):
        self.config = get_config()

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        clean_keyword_list = build_guangdong_first_keyword_list(keywords, industry)
        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()

        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            page = context.new_page()
            try:
                for keyword in clean_keyword_list:
                    if len(result_list) >= collect_limit:
                        break
                    self.goto_search_page(page, keyword)
                    candidate_list = self.extract_candidate_list(page, keyword, industry)
                    if not candidate_list:
                        page.wait_for_timeout(3000)
                        self.assert_public_page_allowed(page)
                        candidate_list = self.extract_candidate_list(page, keyword, industry)
                    for lead in candidate_list:
                        if len(result_list) >= collect_limit:
                            break
                        lead = self.enrich_lead_from_detail(page, lead)
                        if not is_active_public_company_lead(lead):
                            continue
                        if not self.is_guangdong_lead(lead):
                            continue
                        if not is_industry_relevant_public_lead(lead):
                            continue
                        if not has_public_phone_text(lead.phone):
                            continue
                        dedupe_key = self.build_dedupe_key(lead)
                        if dedupe_key in dedupe_key_set:
                            continue
                        dedupe_key_set.add(dedupe_key)
                        result_list.append(lead)
                        self.wait_between_page()
            finally:
                context.close()
        return result_list

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        context_args = {
            "headless": self.config.fengniao_public_web_headless,
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        if self.config.fengniao_public_web_browser_channel:
            context_args["channel"] = self.config.fengniao_public_web_browser_channel
        try:
            return playwright.chromium.launch_persistent_context(
                str(self.config.fengniao_public_web_user_data_dir),
                **context_args,
            )
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured Fengniao browser channel is unavailable, fallback to bundled chromium")
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(
                str(self.config.fengniao_public_web_user_data_dir),
                **context_args,
            )

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.config.fengniao_public_web_user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"美亚风鸟采集专用浏览器资料目录正在被占用，请先关闭采集浏览器后再启动任务。当前占用进程：{process_text}")

    def goto_search_page(self, page, keyword: str) -> None:
        timestamp = int(time.time() * 1000)
        search_url = f"https://www.riskbird.com/search/1?keyword={quote_plus(keyword)}&timestamp={timestamp}"
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=self.config.fengniao_public_web_page_timeout_ms)
            page.wait_for_timeout(2200)
        except PlaywrightTimeoutError:
            logger.warning("Fengniao public search page timeout, url=%s", search_url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("Fengniao public search navigation interrupted, url=%s, error=%s", search_url, self.clean_text(str(ex))[:160])
            page.wait_for_timeout(1600)
        self.assert_public_page_allowed(page)

    def goto_public_url(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.fengniao_public_web_page_timeout_ms)
            page.wait_for_timeout(1600)
        except PlaywrightTimeoutError:
            logger.warning("Fengniao public detail page timeout, url=%s", url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning("Fengniao public detail navigation interrupted, url=%s, error=%s", url, self.clean_text(str(ex))[:160])
            page.wait_for_timeout(1600)
        self.assert_public_page_allowed(page)

    def assert_public_page_allowed(self, page) -> None:
        blocked_reason = self.get_blocked_reason(page)
        if not blocked_reason:
            return
        if self.config.fengniao_public_web_manual_verify_enabled:
            self.wait_for_manual_recovery(page, blocked_reason)
            return
        raise RuntimeError(f"{blocked_reason}，已停止采集")

    def get_blocked_reason(self, page) -> str:
        page_url = page.url.lower()
        page_text = self.get_page_text(page)[:4000]
        if any(token in page_url for token in self.BLOCKED_URL_TOKEN_LIST):
            return "美亚风鸟公开页面跳转到登录页"
        if self.is_login_dialog_visible(page):
            return "美亚风鸟页面出现登录/注册弹窗"
        if any(token in page_text for token in self.BLOCKED_TEXT_TOKEN_LIST):
            return "美亚风鸟公开页面出现登录/验证/额度要求"
        return ""

    def is_login_dialog_visible(self, page) -> bool:
        try:
            return bool(
                page.evaluate(
                    """
                    () => {
                      const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none'
                          && style.visibility !== 'hidden'
                          && rect.width > 80
                          && rect.height > 80;
                      };
                      const elementList = Array.from(document.querySelectorAll('div, section, form'));
                      return elementList.some((element) => {
                        if (!isVisible(element)) {
                          return false;
                        }
                        const text = (element.innerText || '').replace(/\\s+/g, '');
                        return (
                          text.includes('验证码登录/注册')
                          || text.includes('扫码注册/登录')
                          || text.includes('注册即送')
                          || text.includes('免费查询额度')
                          || (text.includes('密码登录') && text.includes('登录/注册'))
                          || (
                            text.includes('登录/注册')
                            && (
                              text.includes('请输入手机号')
                              || text.includes('请输入图片验证码')
                              || text.includes('请输入短信验证码')
                              || text.includes('获取验证码')
                              || text.includes('用户协议')
                              || text.includes('隐私政策')
                            )
                          )
                        );
                      });
                    }
                    """
                )
            )
        except PlaywrightError:
            return False

    def wait_for_manual_recovery(self, page, blocked_reason: str) -> None:
        logger.warning("%s，等待人工完成验证或登录", blocked_reason)
        try:
            page.bring_to_front()
        except PlaywrightError:
            logger.warning("Could not bring Fengniao page to front")

        start_time = time.monotonic()
        timeout_seconds = self.config.fengniao_public_web_manual_verify_timeout_seconds
        poll_seconds = self.config.fengniao_public_web_manual_verify_poll_seconds
        while time.monotonic() - start_time <= timeout_seconds:
            page.wait_for_timeout(int(poll_seconds * 1000))
            if not self.get_blocked_reason(page):
                page.wait_for_timeout(1200)
                logger.info("美亚风鸟页面已人工恢复，继续采集公开页面")
                return
        raise RuntimeError(f"{blocked_reason}，人工验证等待超时，已停止采集")

    def extract_candidate_list(self, page, keyword: str, industry: str) -> List[CollectedLeadDTO]:
        raw_item_list = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/ent/"]')).slice(0, 600).map((element) => {
              const card = element.closest(
                'tr, li, section, div[class*="list"], div[class*="item"], div[class*="card"], div[class*="result"]'
              );
              const parent = card || element.parentElement;
              return {
                href: element.href || '',
                text: (element.innerText || '').trim(),
                title: (element.getAttribute('title') || '').trim(),
                parentText: ((parent && parent.innerText) || '').trim().slice(0, 1600)
              };
            })
            """
        )
        lead_list = []
        for raw_item in raw_item_list:
            lead = self.build_lead(keyword, industry, raw_item)
            if lead is not None:
                lead_list.append(lead)
        return self.dedupe_lead_list(lead_list)

    def build_lead(self, keyword: str, industry: str, raw_item: Dict) -> Optional[CollectedLeadDTO]:
        href = self.normalize_url(raw_item.get("href", ""))
        if not self.is_valid_fengniao_url(href):
            return None
        merged_text = self.clean_text(
            " ".join(
                [
                    raw_item.get("text", ""),
                    raw_item.get("title", ""),
                    raw_item.get("parentText", ""),
                ]
            )
        )
        company_name = clean_company_name_text(self.extract_company_name(merged_text))
        if not company_name:
            return None
        phone = self.extract_phone(merged_text)
        registered_address = self.extract_registered_address(merged_text)
        return CollectedLeadDTO(
            source_type=SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,
            source_keyword=keyword,
            industry=industry,
            suspected_company_name=company_name,
            company_status=self.extract_company_status(merged_text),
            product_name=self.extract_product_name(merged_text, keyword, industry),
            contact_name=self.extract_contact_name(merged_text),
            phone=phone,
            phone_source="美亚风鸟公开页可见字段" if phone else "",
            legal_person=self.extract_legal_person(merged_text),
            unified_social_credit_code=self.extract_unified_social_credit_code(merged_text),
            business_scope=self.extract_business_scope(merged_text),
            registered_address=registered_address,
            region_text=merged_text,
            profile_url=href,
            is_enterprise_verified=True,
            commercial_keyword_count=self.count_business_keyword(merged_text),
        )

    def enrich_lead_from_detail(self, page, lead: CollectedLeadDTO) -> CollectedLeadDTO:
        if not self.is_valid_fengniao_url(lead.profile_url):
            return lead
        try:
            self.goto_public_url(page, lead.profile_url)
            self.expand_more_sections(page)
            detail_text = self.clean_text(self.get_page_text(page))
            detail_phone = self.extract_phone(detail_text)
            detail_address = self.extract_registered_address(detail_text)
            detail_contact_name = self.extract_contact_name(detail_text)
            detail_legal_person = self.extract_legal_person(detail_text)
            detail_credit_code = self.extract_unified_social_credit_code(detail_text)
            lead.phone = detail_phone or lead.phone
            lead.phone_source = "美亚风鸟公开页可见字段" if lead.phone else ""
            lead.contact_name = lead.contact_name or detail_contact_name or detail_legal_person or lead.legal_person
            lead.legal_person = detail_legal_person or lead.legal_person
            lead.unified_social_credit_code = detail_credit_code or lead.unified_social_credit_code
            lead.company_status = self.extract_company_status(detail_text) or lead.company_status
            lead.business_scope = self.extract_business_scope(detail_text) or lead.business_scope
            lead.registered_address = detail_address or lead.registered_address
            lead.product_name = self.extract_product_name(detail_text, lead.source_keyword, lead.industry)
            lead.region_text = " ".join([lead.region_text, detail_text[:3000]])
            lead.commercial_keyword_count = max(
                lead.commercial_keyword_count,
                self.count_business_keyword(detail_text),
            )
        except PlaywrightError:
            logger.warning("Fengniao detail page enrich failed, company=%s", lead.suspected_company_name)
        return lead

    def expand_more_sections(self, page) -> None:
        try:
            expand_count = page.evaluate(
                """
                () => {
                  const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && rect.width > 0
                      && rect.height > 0;
                  };
                  const elements = Array.from(document.querySelectorAll('button, a, span, div'))
                    .filter((element) => {
                      const text = (element.innerText || '').trim();
                      if (!isVisible(element) || text.length > 16) {
                        return false;
                      }
                      const parentText = ((element.parentElement && element.parentElement.innerText) || '').slice(0, 120);
                      if (/同电话|同地址|电话|地址|邮箱|关联企业|同.*企业|更多\\s*\\d*/.test(text + parentText)) {
                        return false;
                      }
                      return /^展开$|^展开全部$/.test(text);
                    })
                    .slice(0, 20);
                  elements.forEach((element) => element.click());
                  return elements.length;
                }
                """
            )
            if expand_count > 0:
                page.wait_for_timeout(900)
                self.assert_public_page_allowed(page)
        except PlaywrightError:
            logger.warning("Fengniao expand click failed, continue with visible fields")

    def extract_company_name(self, text: str) -> str:
        for match in self.COMPANY_PATTERN.finditer(text):
            company_name = clean_company_name_text(match.group(1))
            if self.is_valid_company_name(company_name):
                return company_name
        return ""

    def is_valid_company_name(self, company_name: str) -> bool:
        return is_valid_enterprise_name(company_name, self.INVALID_COMPANY_TOKEN_LIST)

    def extract_phone(self, text: str) -> str:
        return clean_public_phone_text(text, include_service=False)

    def extract_contact_name(self, text: str) -> str:
        return extract_contact_name_by_pattern(text)

    def extract_legal_person(self, text: str) -> str:
        match = re.search(r"(?:法定代表人|经营者|投资人|负责人)[:：\s]*([\u4e00-\u9fa5A-Za-z·]{2,20})", text)
        if match:
            return match.group(1).strip()
        return ""

    def extract_unified_social_credit_code(self, text: str) -> str:
        return extract_credit_code_from_text(text)

    def extract_company_status(self, text: str) -> str:
        return extract_public_company_status_text(text)

    def extract_business_scope(self, text: str) -> str:
        return self.extract_after_label(text, ["经营范围"], 260)

    def extract_registered_address(self, text: str) -> str:
        for label in ["注册地址", "企业地址", "联系地址", "通讯地址", "办公地址", "经营场所", "住所", "地址"]:
            value = self.extract_after_label(text, [label], 160)
            if value:
                clean_value = self.clean_registered_address_value(value)
                if clean_value:
                    return clean_value
        embedded_address = self.extract_embedded_json_address(text)
        if embedded_address:
            return embedded_address
        guangdong_match = re.search(r"(广东省?[\u4e00-\u9fa5A-Za-z0-9（）()·\-号栋室层街路镇区县市]{6,120})", text)
        if guangdong_match:
            return self.clean_registered_address_value(guangdong_match.group(1))
        return ""

    def extract_after_label(self, text: str, label_list: List[str], max_length: int) -> str:
        for label in label_list:
            index = text.find(label)
            if index < 0:
                continue
            value = text[index + len(label): index + len(label) + max_length]
            value = re.sub(r"^[：:\s]+", "", value)
            value = re.split(
                r"(?=法定代表人|经营者|投资人|注册资本|成立日期|登记状态|经营状态|统一社会信用代码|"
                r"股东|主要人员|变更记录|联系方式|联系电话|电话|手机|邮箱|官网|网址|附近企业|地图|风险)",
                value,
            )[0]
            return value.strip(" ：:，,；;。")
        return ""

    def clean_registered_address_value(self, value: str) -> str:
        clean_value = self.clean_text(value)
        embedded_address = self.extract_embedded_json_address(clean_value)
        if embedded_address:
            return embedded_address
        clean_value = re.split(
            r"(?=法定代表人|经营者|投资人|注册资本|成立日期|登记状态|经营状态|统一社会信用代码|"
            r"股东|主要人员|变更记录|联系方式|联系电话|电话|手机|邮箱|官网|网址|附近企业|地图|风险|经营范围|通信地址|"
            r"\"sourceDisplayWeight\"|\"reportYear\"|\"longitude\"|\"latitude\"|\"fromTime\"|\"showSource\"|\"companyOrgType\"|\"actualC)",
            clean_value,
        )[0]
        if self.is_map_json_address_noise(clean_value):
            return ""
        return clean_registered_address_text(clean_value)

    def extract_embedded_json_address(self, text: str) -> str:
        clean_text = self.clean_text(text)
        for pattern in [
            r'"(?:address|regLocation|regAddress|businessAddress)"\s*:\s*"(?P<address>[^"]{6,180})"',
            r"'(?:address|regLocation|regAddress|businessAddress)'\s*:\s*'(?P<address>[^']{6,180})'",
        ]:
            for match in re.finditer(pattern, clean_text):
                address = self.clean_registered_address_value_without_json(match.group("address"))
                if address and re.search(r"[\u4e00-\u9fa5]", address):
                    return address
        return ""

    def clean_registered_address_value_without_json(self, value: str) -> str:
        clean_value = self.clean_text(value)
        clean_value = re.split(
            r"(?=法定代表人|经营者|投资人|注册资本|成立日期|登记状态|经营状态|统一社会信用代码|"
            r"股东|主要人员|变更记录|联系方式|联系电话|电话|手机|邮箱|官网|网址|附近企业|地图|风险|经营范围|通信地址|"
            r"\"sourceDisplayWeight\"|\"reportYear\"|\"longitude\"|\"latitude\"|\"fromTime\"|\"showSource\"|\"companyOrgType\"|\"actualC)",
            clean_value,
        )[0]
        return clean_registered_address_text(clean_value)

    def is_map_json_address_noise(self, value: str) -> bool:
        map_token_list = [
            '"sourceDisplayWeight"',
            '"reportYear"',
            '"longitude"',
            '"latitude"',
            '"fromTime"',
            '"showSource"',
            '"companyOrgType"',
            '"actualC',
        ]
        return has_any_token(value or "", map_token_list)

    def extract_product_name(self, text: str, keyword: str, industry: str) -> str:
        business_scope = self.extract_business_scope(text)
        if business_scope:
            return business_scope[:100]
        labeled_text = extract_public_labeled_business_text(text)
        for token in INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry]):
            if token and token in labeled_text:
                return token
        return ""

    def count_business_keyword(self, text: str) -> int:
        return sum(1 for keyword in self.BUSINESS_KEYWORD_LIST if keyword in text)

    def is_guangdong_lead(self, lead: CollectedLeadDTO) -> bool:
        return is_reliable_guangdong_public_lead(lead)

    def get_page_text(self, page) -> str:
        try:
            return page.locator("body").inner_text(timeout=5000)
        except PlaywrightError:
            return ""

    def normalize_url(self, url: str) -> str:
        clean_url = (url or "").strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        if clean_url.startswith("/"):
            return f"https://www.riskbird.com{clean_url}"
        return clean_url

    def is_valid_fengniao_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        parsed_url = urlparse(url)
        return parsed_url.netloc.lower().endswith("riskbird.com") and "/ent/" in parsed_url.path

    def is_browser_channel_unavailable(self, ex: PlaywrightError) -> bool:
        message = str(ex).lower()
        return "executable doesn't exist" in message or "not found" in message

    def is_recoverable_navigation_error(self, ex: PlaywrightError) -> bool:
        message = str(ex)
        return "net::ERR_ABORTED" in message or "frame was detached" in message

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self.clean_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"美亚风鸟公开页采集浏览器启动失败：{message}"

    def clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def build_dedupe_key(self, lead: CollectedLeadDTO) -> str:
        return lead.suspected_company_name or lead.profile_url

    def dedupe_lead_list(self, lead_list: List[CollectedLeadDTO]) -> List[CollectedLeadDTO]:
        result_list = []
        dedupe_key_set = set()
        for lead in lead_list:
            dedupe_key = self.build_dedupe_key(lead)
            if not dedupe_key or dedupe_key in dedupe_key_set:
                continue
            dedupe_key_set.add(dedupe_key)
            result_list.append(lead)
        return result_list

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result_list = []
        dedupe_set = set()
        for text in text_list:
            clean_text = text.strip()
            if not clean_text or clean_text in dedupe_set:
                continue
            dedupe_set.add(clean_text)
            result_list.append(clean_text)
        return result_list

    def wait_between_page(self) -> None:
        time.sleep(self.config.fengniao_public_web_request_interval_seconds)


@dataclass(frozen=True)
class ShareholderInfo:
    name: str
    share_ratio: float
    is_person: bool


COMPANY_SHAREHOLDER_TOKEN_TUPLE = (
    "公司",
    "集团",
    "企业",
    "合伙",
    "中心",
    "厂",
    "店",
    "商行",
    "经营部",
    "工作室",
    "基金",
    "投资",
    "合作社",
    "有限合伙",
)
SHAREHOLDER_PERSON_DESCRIPTION_TOKEN_TUPLE = ("自然人股东", "自然人")
SHAREHOLDER_PERSON_DESCRIPTION_PATTERN = re.compile(r"[（(]\s*(?:自然人股东|自然人)\s*[）)]")
SHAREHOLDER_ROLE_PERSON_NAME_PATTERN = re.compile(
    r"(?:^|[；;])\s*(?:法人/最大股东|法人|最大股东)\s*[：:]\s*([^；;]+)"
)
SHAREHOLDER_AMOUNT_UNIT_NAME_SET = {
    "万元",
    "万",
    "元",
    "人民币",
    "金额",
    "出资额",
    "认缴",
    "实缴",
    "认缴出资",
    "实缴出资",
    "持股比例",
    "出资比例",
}
SHAREHOLDER_AMOUNT_UNIT_NAME_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)?)*(?:万|万元|元|人民币|金额|出资额|认缴|实缴|认缴出资|实缴出资)$"
)


def clean_mobile_public_phone_text(text: str) -> str:
    return clean_public_phone_text(text, include_service=False, include_landline=False)


def parse_share_ratio_text(text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*[%％]", text or "")
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def normalize_shareholder_person_name(name: str) -> str:
    raw_name = name or ""
    role_match = SHAREHOLDER_ROLE_PERSON_NAME_PATTERN.search(raw_name)
    if role_match:
        raw_name = role_match.group(1)
    clean_name = SHAREHOLDER_PERSON_DESCRIPTION_PATTERN.sub("", raw_name)
    for token in SHAREHOLDER_PERSON_DESCRIPTION_TOKEN_TUPLE:
        clean_name = clean_name.replace(token, "")
    clean_name = re.sub(r"\s+", "", clean_name).strip(" ：:，,；;。()（）[]【】<>《》")
    if clean_name in SHAREHOLDER_AMOUNT_UNIT_NAME_SET:
        return ""
    if SHAREHOLDER_AMOUNT_UNIT_NAME_PATTERN.fullmatch(clean_name):
        return ""
    return normalize_contact_name(clean_name)


def is_person_shareholder_name(name: str) -> bool:
    raw_name = name or ""
    if any(token in raw_name for token in COMPANY_SHAREHOLDER_TOKEN_TUPLE):
        return False
    clean_name = normalize_shareholder_person_name(raw_name)
    if not clean_name:
        return False
    if any(token in clean_name for token in COMPANY_SHAREHOLDER_TOKEN_TUPLE):
        return False
    return is_valid_contact_name(clean_name)


def pick_max_person_shareholder(shareholder_list: List[ShareholderInfo]) -> Optional[ShareholderInfo]:
    person_shareholder_list = []
    for shareholder in shareholder_list:
        clean_name = normalize_shareholder_person_name(shareholder.name)
        if not clean_name:
            continue
        if not shareholder.is_person and not is_person_shareholder_name(clean_name):
            continue
        person_shareholder_list.append(
            ShareholderInfo(
                name=clean_name,
                share_ratio=shareholder.share_ratio,
                is_person=True,
            )
        )
    if not person_shareholder_list:
        return None
    return max(person_shareholder_list, key=lambda shareholder: shareholder.share_ratio)


def format_legal_shareholder_contact_name(legal_person: str, max_shareholder: Optional[ShareholderInfo]) -> str:
    clean_legal_person = normalize_shareholder_person_name(legal_person)
    if not clean_legal_person:
        return ""
    if not max_shareholder or not max_shareholder.is_person:
        return f"法人：{clean_legal_person}"

    clean_shareholder_name = normalize_shareholder_person_name(max_shareholder.name)
    if not clean_shareholder_name:
        return f"法人：{clean_legal_person}"
    if clean_shareholder_name == clean_legal_person:
        return f"法人/最大股东：{clean_legal_person}"
    return f"法人：{clean_legal_person}；最大股东：{clean_shareholder_name}"


class EnterprisePublicWebCollector(FengniaoPublicWebCollector):
    COMMON_BLOCKED_TEXT_TOKEN_LIST = [
        "请完成验证",
        "安全验证",
        "拖动滑块",
        "请输入验证码",
        "访问过于频繁",
        "访问被拒绝",
        "异常请求",
        "网络安全",
        "请进行身份验证以继续使用",
        "点击按钮开始验证",
        "身份验证",
        "免费查询额度",
        "今日查询额度",
    ]

    def __init__(
        self,
        source_type: str,
        display_name: str,
        base_url: str,
        profile_dir_name: str,
        search_url_template_list: List[str],
        host_suffix_list: List[str],
        detail_path_token_list: List[str],
        invalid_company_token_list: List[str],
    ):
        super().__init__()
        self.source_type = source_type
        self.display_name = display_name
        self.base_url = base_url.rstrip("/")
        self.profile_dir_name = profile_dir_name
        self.search_url_template_list = search_url_template_list
        self.host_suffix_list = host_suffix_list
        self.detail_path_token_list = detail_path_token_list
        self.invalid_company_token_list = invalid_company_token_list
        self.user_data_dir = self.config.qcc_public_web_user_data_dir.parent / profile_dir_name
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None
        self.stop_requested_callback: Optional[Callable[[], bool]] = None
        self.existing_dedupe_key_set = set()

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback

    def set_stop_requested_callback(self, callback: Callable[[], bool]) -> None:
        self.stop_requested_callback = callback

    def is_stop_requested(self) -> bool:
        if self.stop_requested_callback is None:
            return False
        try:
            return bool(self.stop_requested_callback())
        except Exception:
            logger.warning("%s stop callback failed", self.display_name)
            return False

    def raise_if_stop_requested(self) -> None:
        if self.is_stop_requested():
            raise RuntimeError(f"用户已停止{self.display_name}反证任务")

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        try:
            self.task_event_callback(event_type, level, message)
        except Exception:
            logger.warning("%s task event callback failed", self.display_name)

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.existing_dedupe_key_set = set()
        for identity in identity_list:
            for field_name in ("company_name", "suspected_company_name", "profile_url", "shop_url"):
                dedupe_key = self.normalize_existing_dedupe_text(identity.get(field_name, ""))
                if dedupe_key:
                    self.existing_dedupe_key_set.add(dedupe_key)

    def normalize_existing_dedupe_text(self, value: str) -> str:
        clean_value = clean_company_name_text(value)
        if clean_value:
            return clean_value
        return self.clean_text(value)

    def is_existing_lead(self, lead: CollectedLeadDTO) -> bool:
        if not self.existing_dedupe_key_set:
            return False
        for value in (lead.suspected_company_name, lead.profile_url, lead.shop_url):
            dedupe_key = self.normalize_existing_dedupe_text(value)
            if dedupe_key and dedupe_key in self.existing_dedupe_key_set:
                return True
        return False

    def remember_collected_lead_identity(self, lead: CollectedLeadDTO) -> None:
        for value in (lead.suspected_company_name, lead.profile_url, lead.shop_url):
            dedupe_key = self.normalize_existing_dedupe_text(value)
            if dedupe_key:
                self.existing_dedupe_key_set.add(dedupe_key)

    def wait_after_collected_lead(self, collected_count: int, collect_limit: int) -> None:
        if should_wait_for_batch_cooldown(
            collected_count,
            collect_limit,
            self.config.collector_batch_size,
            self.config.collector_batch_cooldown_seconds,
        ):
            wait_text = format_wait_seconds(self.config.collector_batch_cooldown_seconds)
            self.emit_task_event(
                "collecting",
                "info",
                f"{self.display_name}已采集 {collected_count} 条，暂停 {wait_text} 秒后继续下一批。",
            )
            time.sleep(self.config.collector_batch_cooldown_seconds)
            return
        if collected_count < collect_limit:
            self.wait_between_page()

    @classmethod
    def create_aiqicha_collector(cls):
        return cls(
            source_type=SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
            display_name="爱企查",
            base_url="https://aiqicha.baidu.com",
            profile_dir_name="aiqicha",
            search_url_template_list=[
                "https://aiqicha.baidu.com/s?q={keyword}&t=0",
                "https://aiqicha.baidu.com/s?q={keyword}",
            ],
            host_suffix_list=["aiqicha.baidu.com", "baidu.com"],
            detail_path_token_list=["/company_detail_"],
            invalid_company_token_list=["爱企查", "百度", "登录", "注册", "搜索", "验证码"],
        )

    @classmethod
    def create_qixin_collector(cls):
        return cls(
            source_type=SOURCE_TYPE_QIXIN_PUBLIC_WEB,
            display_name="启信宝",
            base_url="https://www.qixin.com",
            profile_dir_name="qixin",
            search_url_template_list=[
                "https://www.qixin.com/search?key={keyword}",
                "https://www.qixin.com/search?keyword={keyword}",
            ],
            host_suffix_list=["qixin.com"],
            detail_path_token_list=["/company/"],
            invalid_company_token_list=["启信宝", "登录", "注册", "搜索", "验证码"],
        )

    @classmethod
    def create_tianyancha_collector(cls):
        return cls(
            source_type=SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
            display_name="天眼查",
            base_url="https://www.tianyancha.com",
            profile_dir_name="tianyancha",
            search_url_template_list=[
                "https://www.tianyancha.com/search?key={keyword}",
                "https://www.tianyancha.com/search?base=hub&key={keyword}",
            ],
            host_suffix_list=["tianyancha.com"],
            detail_path_token_list=["/company/"],
            invalid_company_token_list=["天眼查", "登录", "注册", "搜索", "验证码"],
        )

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")

        clean_keyword_list = build_guangdong_first_keyword_list(keywords, industry, include_raw_keyword=False)
        clean_keyword_list = clean_keyword_list[: max(2, min(len(clean_keyword_list), collect_limit * 2))]
        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        detail_visit_count = 0
        max_detail_visit_count = max(collect_limit, collect_limit * 3)

        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            page = context.new_page()
            try:
                for keyword in clean_keyword_list:
                    if len(result_list) >= collect_limit:
                        break
                    candidate_list = []
                    for search_url in self.build_search_url_list(keyword):
                        self.goto_search_url(page, search_url)
                        candidate_list = self.extract_candidate_list(page, keyword, industry)
                        if not candidate_list:
                            page.wait_for_timeout(3200)
                            self.assert_public_page_allowed(page)
                            candidate_list = self.extract_candidate_list(page, keyword, industry)
                        if candidate_list:
                            break
                    if not candidate_list:
                        candidate_list = self.extract_candidate_list_from_visible_text(page, keyword, industry)
                    for lead in candidate_list:
                        if len(result_list) >= collect_limit:
                            break
                        if not self.is_candidate_worth_detail(lead):
                            continue
                        if not is_active_public_company_lead(lead):
                            continue
                        if is_disqualified_public_lead(lead):
                            continue
                        if self.should_defer_detail_enrichment():
                            dedupe_key = self.build_dedupe_key(lead)
                            if dedupe_key in dedupe_key_set:
                                continue
                            if self.is_existing_lead(lead):
                                continue
                            dedupe_key_set.add(dedupe_key)
                            result_list.append(lead)
                            self.remember_collected_lead_identity(lead)
                            self.wait_after_collected_lead(len(result_list), collect_limit)
                            continue
                        if has_public_phone_text(lead.phone):
                            dedupe_key = self.build_dedupe_key(lead)
                            if dedupe_key in dedupe_key_set:
                                continue
                            if self.is_existing_lead(lead):
                                continue
                            dedupe_key_set.add(dedupe_key)
                            result_list.append(lead)
                            self.remember_collected_lead_identity(lead)
                            self.wait_after_collected_lead(len(result_list), collect_limit)
                            continue
                        if detail_visit_count >= max_detail_visit_count:
                            break
                        detail_visit_count += 1
                        lead = self.enrich_lead_from_detail(page, lead)
                        if not is_active_public_company_lead(lead):
                            continue
                        if not self.is_guangdong_lead(lead):
                            continue
                        if not is_industry_relevant_public_lead(lead):
                            continue
                        if not has_public_phone_text(lead.phone):
                            continue
                        if is_disqualified_public_lead(lead):
                            continue
                        dedupe_key = self.build_dedupe_key(lead)
                        if dedupe_key in dedupe_key_set:
                            continue
                        if self.is_existing_lead(lead):
                            continue
                        dedupe_key_set.add(dedupe_key)
                        result_list.append(lead)
                        self.remember_collected_lead_identity(lead)
                        self.wait_after_collected_lead(len(result_list), collect_limit)
            finally:
                context.close()
        return result_list

    def should_defer_detail_enrichment(self) -> bool:
        return self.source_type == SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB

    def collect_by_company_names(
        self,
        industry: str,
        company_name_list: List[str],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")
        self.raise_if_stop_requested()

        clean_company_name_list = []
        for company_name in company_name_list:
            clean_company_name = clean_company_name_text(company_name)
            if not clean_company_name or clean_company_name in clean_company_name_list:
                continue
            clean_company_name_list.append(clean_company_name)

        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            page = context.new_page()
            try:
                for company_name in clean_company_name_list:
                    self.raise_if_stop_requested()
                    if len(result_list) >= collect_limit:
                        break
                    candidate_list = []
                    for search_url in self.build_search_url_list(company_name):
                        self.raise_if_stop_requested()
                        self.goto_search_url(page, search_url)
                        self.raise_if_stop_requested()
                        candidate_list = self.extract_candidate_list(page, company_name, industry)
                        if not candidate_list:
                            page.wait_for_timeout(2400)
                            self.assert_public_page_allowed(page)
                            candidate_list = self.extract_candidate_list(page, company_name, industry)
                        if candidate_list:
                            break
                    if not candidate_list:
                        candidate_list = self.extract_candidate_list_from_visible_text(page, company_name, industry)
                    lead = self.pick_best_company_match(company_name, candidate_list)
                    if lead is None:
                        continue
                    self.raise_if_stop_requested()
                    lead = self.enrich_lead_from_detail(page, lead)
                    self.raise_if_stop_requested()
                    lead.source_keyword = company_name
                    lead.source_type = self.source_type
                    if not is_active_public_company_lead(lead):
                        continue
                    if not self.has_enrichment_value(lead):
                        continue
                    dedupe_key = self.build_dedupe_key(lead)
                    if dedupe_key in dedupe_key_set:
                        continue
                    dedupe_key_set.add(dedupe_key)
                    result_list.append(lead)
                    self.wait_after_collected_lead(len(result_list), collect_limit)
            finally:
                context.close()
        return result_list

    def pick_best_company_match(
        self,
        company_name: str,
        candidate_list: List[CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        if not candidate_list:
            return None
        clean_company_name = self.normalize_company_match_key(company_name)
        for lead in candidate_list:
            if self.normalize_company_match_key(lead.suspected_company_name) == clean_company_name:
                return lead
        return None

    @staticmethod
    def normalize_company_match_key(company_name: str) -> str:
        clean_name = clean_company_name_text(company_name)
        clean_name = re.sub(r"[（(][^（）()]{1,40}[）)]", "", clean_name)
        clean_name = re.sub(r"[\s·•\-—_()（）]+", "", clean_name)
        return clean_name

    def has_enrichment_value(self, lead: CollectedLeadDTO) -> bool:
        return any(
            [
                has_public_phone_text(lead.phone),
                is_valid_contact_name(lead.contact_name),
                is_valid_contact_name(lead.legal_person),
                bool(lead.registered_address),
                bool(lead.unified_social_credit_code),
                bool(lead.business_scope),
                bool(lead.company_status),
            ]
        )

    def is_candidate_worth_detail(self, lead: CollectedLeadDTO) -> bool:
        if not is_active_public_company_lead(lead):
            return False
        if not self.is_guangdong_lead(lead):
            return False
        return is_industry_relevant_public_lead(lead)

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        context_args = {
            "headless": self.config.qcc_public_web_headless,
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        if self.config.qcc_public_web_browser_channel:
            context_args["channel"] = self.config.qcc_public_web_browser_channel
        try:
            return playwright.chromium.launch_persistent_context(str(self.user_data_dir), **context_args)
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            logger.warning("Configured %s browser channel is unavailable, fallback to bundled chromium", self.display_name)
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(str(self.user_data_dir), **context_args)

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"{self.display_name}采集专用浏览器资料目录正在被占用，请先关闭采集浏览器后再启动任务。当前占用进程：{process_text}")

    def build_search_url_list(self, keyword: str) -> List[str]:
        encoded_keyword = quote_plus(keyword)
        return [template.format(keyword=encoded_keyword) for template in self.search_url_template_list]

    def goto_search_url(self, page, search_url: str) -> None:
        self.raise_if_stop_requested()
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
            wait_for_page_timeout_with_jitter(page, 2500, 0.35, 1400)
            self.scroll_search_page_to_load(page)
        except PlaywrightTimeoutError:
            logger.warning("%s public search page timeout, url=%s", self.display_name, search_url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning(
                "%s public search navigation interrupted, url=%s, error=%s",
                self.display_name,
                search_url,
                self.clean_text(str(ex))[:160],
            )
            wait_for_page_timeout_with_jitter(page, 1800, 0.35, 1000)
        self.assert_public_page_allowed(page)
        self.raise_if_stop_requested()

    def scroll_search_page_to_load(self, page) -> None:
        try:
            page.evaluate(
                """
                async () => {
                  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                  for (let index = 0; index < 4; index += 1) {
                    window.scrollBy(0, Math.max(650, window.innerHeight * 0.8));
                    await sleep(500);
                  }
                  window.scrollTo(0, 0);
                  await sleep(350);
                }
                """
            )
        except PlaywrightError:
            logger.warning("%s search page scroll failed", self.display_name)

    def goto_search_page(self, page, keyword: str) -> None:
        self.goto_search_url(page, self.build_search_url_list(keyword)[0])

    def goto_public_url(self, page, url: str) -> None:
        self.raise_if_stop_requested()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
            wait_for_page_timeout_with_jitter(page, 1800, 0.35, 1000)
        except PlaywrightTimeoutError:
            logger.warning("%s public detail page timeout, url=%s", self.display_name, url)
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise
            logger.warning(
                "%s public detail navigation interrupted, url=%s, error=%s",
                self.display_name,
                url,
                self.clean_text(str(ex))[:160],
            )
            wait_for_page_timeout_with_jitter(page, 1800, 0.35, 1000)
        self.assert_public_page_allowed(page)
        self.raise_if_stop_requested()

    def assert_public_page_allowed(self, page) -> None:
        blocked_reason = self.get_blocked_reason(page)
        if not blocked_reason:
            return
        if self.config.qcc_public_web_manual_verify_enabled:
            self.wait_for_manual_recovery(page, blocked_reason)
            return
        raise RuntimeError(f"{blocked_reason}，已停止采集")

    def get_blocked_reason(self, page) -> str:
        page_url = page.url.lower()
        page_text = self.get_page_text(page)[:5000]
        if any(token in page_url for token in ["login", "passport", "captcha", "verify", "auth"]):
            return f"{self.display_name}公开页面跳转到登录/验证页"
        if self.is_login_dialog_visible(page):
            return f"{self.display_name}页面出现登录/注册弹窗"
        if "请进行身份验证以继续使用" in page_text or "点击按钮开始验证" in page_text:
            return f"{self.display_name}公开页面出现身份验证要求"
        if any(token in page_text for token in self.COMMON_BLOCKED_TEXT_TOKEN_LIST):
            return f"{self.display_name}公开页面出现登录/验证/风控要求"
        return ""

    def wait_for_manual_recovery(self, page, blocked_reason: str) -> None:
        logger.warning("%s，等待人工完成验证或登录", blocked_reason)
        self.emit_task_event(
            "waiting_manual",
            "warning",
            f"{blocked_reason}；请在弹出的浏览器中手动完成验证，完成后保持页面打开，系统会自动继续采集。",
        )
        try:
            page.bring_to_front()
        except PlaywrightError:
            logger.warning("Could not bring %s page to front", self.display_name)

        start_time = time.monotonic()
        timeout_seconds = max(self.config.qcc_public_web_manual_verify_timeout_seconds, 1800)
        poll_seconds = self.config.qcc_public_web_manual_verify_poll_seconds
        while time.monotonic() - start_time <= timeout_seconds:
            self.raise_if_stop_requested()
            page.wait_for_timeout(int(poll_seconds * 1000))
            self.raise_if_stop_requested()
            if not self.get_blocked_reason(page):
                page.wait_for_timeout(1200)
                logger.info("%s页面已人工恢复，继续采集公开页面", self.display_name)
                self.emit_task_event(
                    "manual_resumed",
                    "info",
                    f"{self.display_name}人工验证已完成，继续采集公开页面。",
                )
                return
        raise RuntimeError(f"{blocked_reason}，人工验证等待超时，已停止采集")

    def extract_candidate_list(self, page, keyword: str, industry: str) -> List[CollectedLeadDTO]:
        raw_item_list = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href]')).slice(0, 900).map((element) => {
              const card = element.closest(
                'tr, li, section, div[class*="search"], div[class*="result"], div[class*="item"], div[class*="card"], div[class*="company"]'
              );
              const parent = card || element.parentElement;
              return {
                href: element.href || element.getAttribute('href') || '',
                text: (element.innerText || '').trim(),
                title: (element.getAttribute('title') || '').trim(),
                parentText: ((parent && parent.innerText) || '').trim().slice(0, 1800)
              };
            })
            """
        )
        lead_list = []
        for raw_item in raw_item_list:
            lead = self.build_lead(keyword, industry, raw_item)
            if lead is not None:
                lead_list.append(lead)
        return self.dedupe_lead_list(lead_list)

    def extract_candidate_list_from_visible_text(
        self,
        page,
        keyword: str,
        industry: str,
    ) -> List[CollectedLeadDTO]:
        page_text = self.clean_text(self.get_page_text(page))
        lead_list: List[CollectedLeadDTO] = []
        for match in self.COMPANY_PATTERN.finditer(page_text):
            company_name = clean_company_name_text(match.group(1))
            if not self.is_valid_company_name(company_name):
                continue
            chunk = page_text[match.start(): match.start() + 1000]
            phone = self.extract_phone(chunk)
            lead_list.append(
                CollectedLeadDTO(
                    source_type=self.source_type,
                    source_keyword=keyword,
                    industry=industry,
                    suspected_company_name=company_name,
                    company_status=self.extract_company_status(chunk),
                    product_name=self.extract_product_name(chunk, keyword, industry),
                    contact_name=self.extract_contact_name(chunk),
                    phone=phone,
                    phone_source=f"{self.display_name}公开页可见字段" if phone else "",
                    legal_person=self.extract_legal_person(chunk),
                    unified_social_credit_code=self.extract_unified_social_credit_code(chunk),
                    business_scope=self.extract_business_scope(chunk),
                    registered_address=self.extract_registered_address(chunk),
                    region_text=chunk[:3000],
                    profile_url=page.url,
                    is_enterprise_verified=True,
                    commercial_keyword_count=self.count_business_keyword(chunk),
                )
            )
        return self.dedupe_lead_list(lead_list)

    def build_lead(self, keyword: str, industry: str, raw_item: Dict) -> Optional[CollectedLeadDTO]:
        href = self.normalize_url(raw_item.get("href", ""))
        if not self.is_valid_enterprise_url(href):
            return None
        merged_text = self.clean_text(
            " ".join(
                [
                    raw_item.get("text", ""),
                    raw_item.get("title", ""),
                    raw_item.get("parentText", ""),
                ]
            )
        )
        company_name = clean_company_name_text(self.extract_company_name(merged_text))
        if not company_name:
            return None
        phone = self.extract_phone(merged_text)
        return CollectedLeadDTO(
            source_type=self.source_type,
            source_keyword=keyword,
            industry=industry,
            suspected_company_name=company_name,
            company_status=self.extract_company_status(merged_text),
            product_name=self.extract_product_name(merged_text, keyword, industry),
            contact_name=self.extract_contact_name(merged_text),
            phone=phone,
            phone_source=f"{self.display_name}公开页可见字段" if phone else "",
            legal_person=self.extract_legal_person(merged_text),
            unified_social_credit_code=self.extract_unified_social_credit_code(merged_text),
            business_scope=self.extract_business_scope(merged_text),
            registered_address=self.extract_registered_address(merged_text),
            region_text=merged_text,
            profile_url=href,
            is_enterprise_verified=True,
            commercial_keyword_count=self.count_business_keyword(merged_text),
        )

    def enrich_lead_from_detail(self, page, lead: CollectedLeadDTO) -> CollectedLeadDTO:
        if not self.is_valid_enterprise_url(lead.profile_url):
            return lead
        try:
            self.goto_public_url(page, lead.profile_url)
            self.expand_more_sections(page)
            self.expand_contact_phone_sections(page)
            if self.should_expand_shareholder_sections():
                self.expand_shareholder_sections(page)
            detail_text_part_list = [
                self.get_page_text(page),
                self.extract_contact_attribute_text(page),
                self.extract_contact_script_text(page),
            ]
            if self.should_collect_shareholder_contact():
                detail_text_part_list.append(self.extract_shareholder_attribute_text(page))
            detail_text = self.clean_text(" ".join(detail_text_part_list))
            detail_phone = self.extract_phone(detail_text)
            detail_address = self.extract_registered_address(detail_text)
            detail_contact_name = self.extract_contact_name(detail_text)
            detail_legal_person = self.extract_legal_person(detail_text)
            detail_credit_code = self.extract_unified_social_credit_code(detail_text)
            role_contact_name = ""
            if self.should_collect_shareholder_contact():
                max_person_shareholder = self.extract_max_person_shareholder(detail_text)
                role_contact_name = format_legal_shareholder_contact_name(
                    detail_legal_person or lead.legal_person,
                    max_person_shareholder,
                )
            merged_phone = self.merge_phone_text(lead.phone, detail_phone)
            if merged_phone:
                lead.phone = merged_phone
                lead.phone_source = self.merge_text(
                    lead.phone_source,
                    f"{self.display_name}公开页可见字段（含已展开联系方式）",
                )
            lead.contact_name = (
                role_contact_name
                or lead.contact_name
                or detail_contact_name
                or detail_legal_person
                or lead.legal_person
            )
            lead.legal_person = detail_legal_person or lead.legal_person
            lead.unified_social_credit_code = detail_credit_code or lead.unified_social_credit_code
            lead.company_status = self.extract_company_status(detail_text) or lead.company_status
            lead.business_scope = self.extract_business_scope(detail_text) or lead.business_scope
            lead.registered_address = detail_address or lead.registered_address
            lead.product_name = self.extract_product_name(detail_text, lead.source_keyword, lead.industry)
            lead.region_text = " ".join([lead.region_text, detail_text[:3000]])
            lead.commercial_keyword_count = max(
                lead.commercial_keyword_count,
                self.count_business_keyword(detail_text),
            )
        except PlaywrightError:
            logger.warning("%s detail page enrich failed, company=%s", self.display_name, lead.suspected_company_name)
        return lead

    def extract_contact_attribute_text(self, page) -> str:
        try:
            return page.evaluate(
                """
                () => {
                  const usefulPattern = /(电话|手机|联系|号码|tel:|phone|mobile|contact|\\d{3,4}[-\\s]?\\d{7,8}|1[3-9]\\d{9})/i;
                  const nodes = Array.from(document.querySelectorAll('body *')).slice(0, 9000);
                  return nodes
                    .map((element) => {
                      const attrText = Array.from(element.attributes || [])
                        .map((attr) => `${attr.name}=${attr.value}`)
                        .join(' ');
                      const dataText = Object.values(element.dataset || {}).join(' ');
                      const text = (element.innerText || element.textContent || '').trim();
                      const parentText = ((element.parentElement && element.parentElement.innerText) || '').trim().slice(0, 260);
                      const value = [attrText, dataText, text, parentText]
                        .filter(Boolean)
                        .join(' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                      if (!usefulPattern.test(value)) {
                        return '';
                      }
                      return value.slice(0, 900);
                    })
                    .filter(Boolean)
                    .join(' ');
                }
                """
            )
        except PlaywrightError:
            return ""

    def extract_contact_script_text(self, page) -> str:
        try:
            return page.evaluate(
                """
                () => {
                  const phonePattern = /(1[3-9]\\d{9}|\\d{3,4}[-\\s]?\\d{7,8}|400[-\\s]?\\d{3}[-\\s]?\\d{4})/g;
                  const usefulPattern = /(电话|手机|联系|号码|tel:|phone|mobile|contact)/i;
                  const snippets = [];
                  Array.from(document.querySelectorAll('script'))
                    .slice(0, 160)
                    .forEach((element) => {
                      const text = (element.textContent || '').replace(/\\s+/g, ' ').trim();
                      if (!phonePattern.test(text)) {
                        phonePattern.lastIndex = 0;
                        return;
                      }
                      phonePattern.lastIndex = 0;
                      let match;
                      while ((match = phonePattern.exec(text)) && snippets.length < 80) {
                        const start = Math.max(0, match.index - 220);
                        const end = Math.min(text.length, match.index + match[0].length + 260);
                        const snippet = text.slice(start, end);
                        if (usefulPattern.test(snippet) || /1[3-9]\\d{9}/.test(match[0])) {
                          snippets.push(snippet);
                        }
                      }
                    });
                  return snippets.join(' ');
                }
                """
            )
        except PlaywrightError:
            return ""

    def extract_shareholder_attribute_text(self, page) -> str:
        try:
            return page.evaluate("""
                () => {
                  const keywordPattern = /(股东|持股|出资比例|认缴出资|实缴出资|股权结构)/;
                  return Array.from(document.querySelectorAll('section, table, tbody, tr, li, div'))
                    .map(node => (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim())
                    .filter(text => text && text.length <= 800 && keywordPattern.test(text))
                    .slice(0, 80)
                    .join(' ');
                }
            """) or ""
        except PlaywrightError:
            return ""

    def should_collect_shareholder_contact(self) -> bool:
        return self.source_type in {SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB, SOURCE_TYPE_QIXIN_PUBLIC_WEB}

    def should_expand_shareholder_sections(self) -> bool:
        return self.should_collect_shareholder_contact() and bool(
            getattr(self.config, "enterprise_shareholder_expand_enabled", False)
        )

    def expand_contact_phone_sections(self, page) -> None:
        if not self.should_collect_shareholder_contact():
            return
        if self.source_type == SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB and not getattr(
            self.config,
            "tianyancha_contact_expand_enabled",
            False,
        ):
            return
        try:
            for round_index in range(8):
                expand_count = page.evaluate(
                    """
                    () => {
                      if (!window.__codexPhoneRevealRound) {
                        window.__codexPhoneRevealRound = 0;
                      }
                      window.__codexPhoneRevealRound += 1;
                      const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none'
                          && style.visibility !== 'hidden'
                          && rect.width > 0
                          && rect.height > 0;
                      };
                      const isClickable = (element) => {
                        const style = window.getComputedStyle(element);
                        return element.tagName === 'A'
                          || element.tagName === 'BUTTON'
                          || element.getAttribute('role') === 'button'
                          || typeof element.onclick === 'function'
                          || style.cursor === 'pointer';
                      };
                      const revealPattern = /(查看|展开|更多|全部|完整|显示|解锁|打开|点击).{0,14}(电话|号码|手机|联系方式|联系信息|联系资料)|(电话|号码|手机|联系方式|联系信息|联系资料).{0,14}(更多|全部|完整|查看|展开|显示|解锁|打开)|^(联系方式|联系信息|联系资料|联系电话|电话|查看|更多|展开|全部|完整号码)$/;
                      const denyPattern = /(登录|注册|开通|充值|购买|支付|立即咨询|在线咨询|拨打电话|广告|反馈|举报|下载|APP|认证)/;
                      const scoredElements = Array.from(document.querySelectorAll('button, a, span, div, i, em'))
                        .filter((element) => {
                          if (!isVisible(element) || !isClickable(element)) {
                            return false;
                          }
                          const text = (element.innerText || element.textContent || '').replace(/\\s+/g, '');
                          const title = (element.getAttribute('title') || element.getAttribute('aria-label') || '').replace(/\\s+/g, '');
                          const className = String(element.className || '');
                          const parentText = ((element.parentElement && element.parentElement.innerText) || '').replace(/\\s+/g, '').slice(0, 220);
                          const nearbyText = `${text}${title}${parentText}${className}`;
                          if ((!text && !title) || text.length > 48) {
                            return false;
                          }
                          if (denyPattern.test(nearbyText)) {
                            return false;
                          }
                          if (!/(电话|号码|手机|联系方式|联系信息|联系资料|联系)/.test(nearbyText)) {
                            return false;
                          }
                          return revealPattern.test(text) || revealPattern.test(title) || revealPattern.test(parentText);
                        })
                        .map((element) => {
                          const text = (element.innerText || element.textContent || '').replace(/\\s+/g, '');
                          let score = 0;
                          if (/电话|号码|手机/.test(text)) score += 4;
                          if (/全部|完整|更多|展开|查看|显示|解锁/.test(text)) score += 3;
                          if (/联系方式|联系信息|联系资料/.test(text)) score += 2;
                          return { element, score };
                        })
                        .sort((left, right) => right.score - left.score)
                        .slice(0, 48)
                        .map((item) => item.element);
                      let clickedCount = 0;
                      scoredElements.forEach((element) => {
                        try {
                          element.scrollIntoView({ block: 'center', inline: 'nearest' });
                          element.click();
                          clickedCount += 1;
                        } catch (error) {}
                      });
                      return clickedCount;
                    }
                    """
                )
                if round_index < 5:
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(300)
                if expand_count <= 0:
                    break
                page.wait_for_timeout(1600)
                self.assert_public_page_allowed(page)
        except PlaywrightError:
            logger.warning("%s contact phone expand click failed, continue with visible fields", self.display_name)

    def expand_shareholder_sections(self, page) -> None:
        if not self.should_expand_shareholder_sections():
            return
        try:
            for _ in range(4):
                click_count = page.evaluate("""
                    () => {
                      const keywordList = ['股东', '股东信息', '股东及出资', '股权结构', '主要人员'];
                      const nodeList = Array.from(document.querySelectorAll('button, a, span, div'));
                      let clicked = 0;
                      for (const node of nodeList) {
                        const text = (node.innerText || node.textContent || '').replace(/\\s+/g, '');
                        if (!text || text.length > 24) continue;
                        if (!keywordList.some(keyword => text.includes(keyword))) continue;
                        const rect = node.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) continue;
                        node.click();
                        clicked += 1;
                        if (clicked >= 8) break;
                      }
                      return clicked;
                    }
                """)
                if not click_count:
                    break
                page.wait_for_timeout(600)
        except PlaywrightError:
            logger.warning("%s shareholder section expand failed, continue with visible fields", self.display_name)

    def extract_shareholder_info_list(self, text: str) -> List[ShareholderInfo]:
        normalized_text = self.clean_text(text or "")
        if not normalized_text:
            return []
        shareholder_list: List[ShareholderInfo] = []
        ratio_label_pattern = re.compile(r"(?:持股比例|持股|出资比例|认缴比例|股份比例)")
        shareholder_name_noise_set = {
            "股东信息",
            "股东名称",
            "股东",
            "姓名",
            "名称",
            "认缴出资",
            "实缴出资",
            "认缴",
            "实缴",
            "出资额",
            "出资方式",
            "出资日期",
        }
        pattern = re.compile(
            r"(?:^|[\s，,；;。:：])"
            r"(?:股东信息|股东名称|股东|姓名|名称)?"
            r"\s*"
            r"([\u3400-\u9fffA-Za-z0-9·（）()]{2,40})"
            r".{0,24}?"
            r"(?:持股比例|持股|出资比例|认缴比例|股份比例)?"
            r"\s*(\d+(?:\.\d+)?)\s*[%％]"
        )
        for match in pattern.finditer(normalized_text):
            name_context = ratio_label_pattern.split(match.group(0), maxsplit=1)[0]
            raw_name = match.group(1).strip(" ：:，,；;。()（）[]【】<>《》")
            for candidate in reversed(re.findall(r"[\u3400-\u9fffA-Za-z0-9·（）()]{2,40}", name_context)):
                clean_candidate = candidate.strip(" ：:，,；;。()（）[]【】<>《》")
                clean_candidate = re.sub(r"^(?:股东信息|股东名称|股东|姓名|名称)+", "", clean_candidate)
                clean_candidate = re.sub(
                    r"^(?:认缴出资|实缴出资|认缴|实缴|出资额)?\d+(?:\.\d+)?(?:万|万元|元)?",
                    "",
                    clean_candidate,
                )
                clean_candidate = clean_candidate.strip(" ：:，,；;。()（）[]【】<>《》")
                if not clean_candidate or clean_candidate in shareholder_name_noise_set:
                    continue
                if re.fullmatch(r"\d+(?:\.\d+)?(?:万|万元|元)?", clean_candidate):
                    continue
                raw_name = clean_candidate
                break
            ratio = parse_share_ratio_text(match.group(0))
            if not raw_name or ratio <= 0:
                continue
            name = normalize_shareholder_person_name(raw_name) or raw_name
            shareholder_list.append(
                ShareholderInfo(
                    name=name,
                    share_ratio=ratio,
                    is_person=is_person_shareholder_name(name),
                )
            )
        deduped_shareholder_list = []
        seen_name_set = set()
        for shareholder in shareholder_list:
            if shareholder.name in seen_name_set:
                continue
            seen_name_set.add(shareholder.name)
            deduped_shareholder_list.append(shareholder)
        return deduped_shareholder_list

    def extract_max_person_shareholder(self, text: str) -> Optional[ShareholderInfo]:
        return pick_max_person_shareholder(self.extract_shareholder_info_list(text))

    def extract_phone(self, text: str) -> str:
        if self.should_collect_shareholder_contact():
            return clean_mobile_public_phone_text(text)
        return clean_public_phone_text(text, include_service=True)

    def merge_phone_text(self, left_phone: str, right_phone: str) -> str:
        phone_list = []
        phone_list.extend(self.split_phone_text(left_phone))
        phone_list.extend(self.split_phone_text(right_phone))
        return "；".join(self.dedupe_text_list(phone_list))

    def split_phone_text(self, phone_text: str) -> List[str]:
        if self.should_collect_shareholder_contact():
            return split_public_phone_text(phone_text, include_service=False, include_landline=False)
        return split_public_phone_text(phone_text, include_service=True)

    def merge_text(self, left_text: str, right_text: str) -> str:
        text_list = []
        for text in (left_text, right_text):
            clean_text = self.clean_text(text)
            if clean_text:
                text_list.append(clean_text)
        return "；".join(self.dedupe_text_list(text_list))

    def is_valid_company_name(self, company_name: str) -> bool:
        return is_valid_enterprise_name(company_name, self.invalid_company_token_list)

    def normalize_url(self, url: str) -> str:
        clean_url = (url or "").strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        if clean_url.startswith("/"):
            return f"{self.base_url}{clean_url}"
        return clean_url

    def is_valid_fengniao_url(self, url: str) -> bool:
        return self.is_valid_enterprise_url(url)

    def is_valid_enterprise_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        parsed_url = urlparse(url)
        host = parsed_url.netloc.lower()
        path = parsed_url.path.lower()
        if not any(host.endswith(host_suffix) for host_suffix in self.host_suffix_list):
            return False
        if any(token in host or token in path for token in ["login", "passport", "captcha", "verify"]):
            return False
        return any(path_token in path for path_token in self.detail_path_token_list)

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self.clean_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"{self.display_name}公开页采集浏览器启动失败：{message}"

    def wait_between_page(self) -> None:
        sleep_with_jitter(self.config.qcc_public_web_request_interval_seconds, 0.35, 3.0)


class Alibaba1688TianyanchaCollector:
    def __init__(self):
        self.alibaba_collector = Alibaba1688PublicPageCollector()
        self.tianyancha_collector = EnterprisePublicWebCollector.create_tianyancha_collector()
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None

    def __getattr__(self, name: str):
        return getattr(self.alibaba_collector, name)

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback
        self.alibaba_collector.set_task_event_callback(callback)
        self.tianyancha_collector.set_task_event_callback(callback)

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.alibaba_collector.set_existing_lead_identity_list(identity_list)

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        try:
            self.task_event_callback(event_type, level, message)
        except Exception:
            logger.warning("1688+天眼查 task event callback failed")

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        alibaba_lead_list = self.alibaba_collector.collect(industry, keywords, collect_limit)
        if not alibaba_lead_list:
            return alibaba_lead_list

        self.wait_before_tianyancha_enrichment(len(alibaba_lead_list))
        self.emit_task_event(
            "collecting",
            "info",
            f"1688已采集 {len(alibaba_lead_list)} 条公开线索，开始用天眼查公开页按企业名补全联系人和电话。",
        )
        try:
            tianyancha_lead_list = self.tianyancha_collector.collect_by_company_names(
                industry=industry,
                company_name_list=[lead.suspected_company_name for lead in alibaba_lead_list],
                collect_limit=len(alibaba_lead_list),
            )
        except Exception as ex:
            logger.exception("1688 lead Tianyancha enrichment failed, error=%s", ex)
            self.emit_task_event(
                "collecting",
                "warning",
                f"天眼查补全失败，系统将先保留1688已采集线索；原因：{ex}",
            )
            return alibaba_lead_list

        enrichment_map = self.build_enrichment_map(tianyancha_lead_list)
        enriched_count = 0
        phone_enriched_count = 0
        contact_enriched_count = 0
        for alibaba_lead in alibaba_lead_list:
            tianyancha_lead = self.find_enrichment_lead(alibaba_lead.suspected_company_name, enrichment_map)
            if tianyancha_lead is None:
                continue
            before_phone = alibaba_lead.phone
            before_contact_name = alibaba_lead.contact_name
            self.merge_enrichment(alibaba_lead, tianyancha_lead)
            enriched_count += 1
            if not has_public_phone_text(before_phone) and has_public_phone_text(alibaba_lead.phone):
                phone_enriched_count += 1
            if not before_contact_name and alibaba_lead.contact_name:
                contact_enriched_count += 1

        self.emit_task_event(
            "collecting",
            "info",
            f"天眼查补全完成：匹配 {enriched_count} 条，补到电话 {phone_enriched_count} 条，补到联系人/法人 {contact_enriched_count} 条。",
        )
        result_list = []
        for lead in alibaba_lead_list:
            disqualified_reason = get_disqualified_lead_reason(lead)
            if disqualified_reason:
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过非正常状态线索：{lead.suspected_company_name}，原因：{disqualified_reason}",
                )
                continue
            result_list.append(lead)
        return result_list

    def wait_before_tianyancha_enrichment(self, alibaba_lead_count: int) -> None:
        delay_seconds = max(0.0, self.alibaba_collector.config.alibaba_tianyancha_enrich_delay_seconds)
        if delay_seconds <= 0:
            return
        wait_text = format_wait_seconds(delay_seconds)
        self.emit_task_event(
            "collecting",
            "info",
            f"1688已采集 {alibaba_lead_count} 条公开线索，先冷却 {wait_text} 秒，再进入天眼查补全。",
        )
        sleep_with_jitter(delay_seconds, 0.2, delay_seconds)

    def build_enrichment_map(self, tianyancha_lead_list: List[CollectedLeadDTO]) -> Dict[str, CollectedLeadDTO]:
        enrichment_map = {}
        for lead in tianyancha_lead_list:
            clean_name = EnterprisePublicWebCollector.normalize_company_match_key(lead.suspected_company_name)
            if clean_name and clean_name not in enrichment_map:
                enrichment_map[clean_name] = lead
        return enrichment_map

    def find_enrichment_lead(
        self,
        company_name: str,
        enrichment_map: Dict[str, CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        clean_company_name = EnterprisePublicWebCollector.normalize_company_match_key(company_name)
        if clean_company_name in enrichment_map:
            return enrichment_map[clean_company_name]
        return None

    def merge_enrichment(self, target: CollectedLeadDTO, source: CollectedLeadDTO) -> None:
        target.phone = self.merge_phone(target.phone, source.phone)
        if has_public_phone_text(source.phone):
            target.phone_source = self.merge_text(target.phone_source, source.phone_source or "天眼查公开页可见字段")
        elif not has_public_phone_text(target.phone):
            target.phone = ""
            target.phone_source = ""
        enrichment_contact_name = ""
        if is_valid_contact_name(source.contact_name):
            enrichment_contact_name = source.contact_name
        elif is_valid_contact_name(source.legal_person):
            enrichment_contact_name = source.legal_person
        if enrichment_contact_name:
            target.contact_name = enrichment_contact_name
        elif target.contact_name and not is_valid_contact_name(target.contact_name):
            target.contact_name = ""
        target.legal_person = source.legal_person or target.legal_person
        target.company_status = source.company_status or target.company_status
        target.unified_social_credit_code = source.unified_social_credit_code or target.unified_social_credit_code
        target.business_scope = source.business_scope or target.business_scope
        target.registered_address = source.registered_address or target.registered_address
        target.risk_tag = source.risk_tag or target.risk_tag
        target.region_text = self.merge_text(target.region_text, source.region_text)[:3000]
        target.is_enterprise_verified = target.is_enterprise_verified or source.is_enterprise_verified
        target.commercial_keyword_count = max(target.commercial_keyword_count, source.commercial_keyword_count)

    def merge_phone(self, left_phone: str, right_phone: str) -> str:
        return merge_public_phone_text(left_phone, right_phone, include_service=True)

    def split_phone_text(self, phone_text: str) -> List[str]:
        return split_public_phone_text(phone_text, include_service=True)

    def merge_text(self, left_text: str, right_text: str) -> str:
        text_list = []
        if left_text:
            text_list.append(left_text)
        if right_text:
            text_list.append(right_text)
        return "；".join(self.dedupe_text_list(text_list))

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result_list = []
        dedupe_set = set()
        for text in text_list:
            clean_text = (text or "").strip()
            if not clean_text or clean_text in ("未公开", "号码皆未公开") or clean_text in dedupe_set:
                continue
            dedupe_set.add(clean_text)
            result_list.append(clean_text)
        return result_list


class MadeInChinaTianyanchaCollector:
    def __init__(
        self,
        made_in_china_collector: Optional[MadeInChinaPublicPageCollector] = None,
        tianyancha_collector: Optional[EnterprisePublicWebCollector] = None,
    ):
        self.made_in_china_collector = made_in_china_collector or MadeInChinaPublicPageCollector()
        self.tianyancha_collector = tianyancha_collector or EnterprisePublicWebCollector.create_tianyancha_collector()
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None

    def __getattr__(self, name: str):
        return getattr(self.made_in_china_collector, name)

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback
        self.made_in_china_collector.set_task_event_callback(callback)
        self.tianyancha_collector.set_task_event_callback(callback)

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.made_in_china_collector.set_existing_lead_identity_list(identity_list)

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        try:
            self.task_event_callback(event_type, level, message)
        except Exception:
            logger.warning("Made-in-China+Tianyancha task event callback failed")

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        made_in_china_lead_list = self.made_in_china_collector.collect(industry, keywords, collect_limit)
        if not made_in_china_lead_list:
            return made_in_china_lead_list

        self.wait_before_tianyancha_enrichment(len(made_in_china_lead_list))
        self.emit_task_event(
            "collecting",
            "info",
            f"中国制造网已采集 {len(made_in_china_lead_list)} 个企业名，开始用天眼查公开页精准匹配法人、电话和地址。",
        )
        try:
            tianyancha_lead_list = self.tianyancha_collector.collect_by_company_names(
                industry=industry,
                company_name_list=[lead.suspected_company_name for lead in made_in_china_lead_list],
                collect_limit=len(made_in_china_lead_list),
            )
        except Exception as ex:
            logger.warning("Made-in-China lead Tianyancha enrichment failed, error=%s", ex)
            self.emit_task_event(
                "collecting",
                "warning",
                f"天眼查补全失败，系统将先保留中国制造网已采集企业名；原因：{ex}",
            )
            return made_in_china_lead_list

        enrichment_map = self.build_enrichment_map(tianyancha_lead_list)
        enriched_count = 0
        phone_enriched_count = 0
        contact_enriched_count = 0
        for made_in_china_lead in made_in_china_lead_list:
            tianyancha_lead = self.find_enrichment_lead(
                made_in_china_lead.suspected_company_name,
                enrichment_map,
            )
            if tianyancha_lead is None:
                continue
            before_phone = made_in_china_lead.phone
            before_contact_name = made_in_china_lead.contact_name
            self.merge_enrichment(made_in_china_lead, tianyancha_lead)
            enriched_count += 1
            if not has_public_phone_text(before_phone) and has_public_phone_text(made_in_china_lead.phone):
                phone_enriched_count += 1
            if not before_contact_name and made_in_china_lead.contact_name:
                contact_enriched_count += 1

        self.emit_task_event(
            "collecting",
            "info",
            f"天眼查补全完成：匹配 {enriched_count} 条，补到电话 {phone_enriched_count} 条，补到联系人/法人 {contact_enriched_count} 条。",
        )
        result_list = []
        for lead in made_in_china_lead_list:
            disqualified_reason = get_disqualified_lead_reason(lead)
            if disqualified_reason:
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过非正常状态线索：{lead.suspected_company_name}，原因：{disqualified_reason}",
                )
                continue
            result_list.append(lead)
        return result_list

    def wait_before_tianyancha_enrichment(self, lead_count: int) -> None:
        config = getattr(self.made_in_china_collector, "config", None)
        delay_seconds = max(0.0, getattr(config, "alibaba_tianyancha_enrich_delay_seconds", 0.0))
        if delay_seconds <= 0:
            return
        wait_text = format_wait_seconds(delay_seconds)
        self.emit_task_event(
            "collecting",
            "info",
            f"中国制造网已采集 {lead_count} 个企业名，先冷却 {wait_text} 秒，再进入天眼查补全。",
        )
        sleep_with_jitter(delay_seconds, 0.2, delay_seconds)

    def build_enrichment_map(self, tianyancha_lead_list: List[CollectedLeadDTO]) -> Dict[str, CollectedLeadDTO]:
        enrichment_map = {}
        for lead in tianyancha_lead_list:
            clean_name = EnterprisePublicWebCollector.normalize_company_match_key(lead.suspected_company_name)
            if clean_name and clean_name not in enrichment_map:
                enrichment_map[clean_name] = lead
        return enrichment_map

    def find_enrichment_lead(
        self,
        company_name: str,
        enrichment_map: Dict[str, CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        clean_company_name = EnterprisePublicWebCollector.normalize_company_match_key(company_name)
        if clean_company_name in enrichment_map:
            return enrichment_map[clean_company_name]
        return None

    def merge_enrichment(self, target: CollectedLeadDTO, source: CollectedLeadDTO) -> None:
        target.phone = self.merge_phone(target.phone, source.phone)
        if has_public_phone_text(source.phone):
            target.phone_source = self.merge_text(target.phone_source, source.phone_source or "天眼查公开页可见字段")
        elif not has_public_phone_text(target.phone):
            target.phone = ""
            target.phone_source = ""
        enrichment_contact_name = ""
        if is_valid_contact_name(source.contact_name):
            enrichment_contact_name = source.contact_name
        elif is_valid_contact_name(source.legal_person):
            enrichment_contact_name = source.legal_person
        if enrichment_contact_name:
            target.contact_name = enrichment_contact_name
        elif target.contact_name and not is_valid_contact_name(target.contact_name):
            target.contact_name = ""
        target.legal_person = source.legal_person or target.legal_person
        target.company_status = source.company_status or target.company_status
        target.unified_social_credit_code = source.unified_social_credit_code or target.unified_social_credit_code
        target.business_scope = source.business_scope or target.business_scope
        target.registered_address = source.registered_address or target.registered_address
        target.risk_tag = source.risk_tag or target.risk_tag
        target.region_text = self.merge_text(target.region_text, source.region_text)[:3000]
        target.is_enterprise_verified = target.is_enterprise_verified or source.is_enterprise_verified
        target.commercial_keyword_count = max(target.commercial_keyword_count, source.commercial_keyword_count)

    def merge_phone(self, left_phone: str, right_phone: str) -> str:
        return merge_public_phone_text(left_phone, right_phone, include_service=True)

    def merge_text(self, left_text: str, right_text: str) -> str:
        text_list = []
        if left_text:
            text_list.append(left_text)
        if right_text:
            text_list.append(right_text)
        return "；".join(self.dedupe_text_list(text_list))

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result_list = []
        dedupe_set = set()
        for text in text_list:
            clean_text = (text or "").strip()
            if not clean_text or clean_text in ("未公开", "号码皆未公开") or clean_text in dedupe_set:
                continue
            dedupe_set.add(clean_text)
            result_list.append(clean_text)
        return result_list


class AiWebSearchCollector:
    def __init__(self):
        self.config = get_config()
        self.ai_service = DeepSeekAiService()
        self.web_search_service = PublicWebSearchService()
        self.alibaba_collector = Alibaba1688PublicPageCollector()
        self.tianyancha_collector = EnterprisePublicWebCollector.create_tianyancha_collector()
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None
        self.existing_dedupe_key_set = set()
        self.last_collect_diagnostic = ""

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback
        self.alibaba_collector.set_task_event_callback(callback)
        self.tianyancha_collector.set_task_event_callback(callback)

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.existing_dedupe_key_set = set()
        for identity in identity_list:
            for field_name in ("company_name", "suspected_company_name", "profile_url", "shop_url"):
                dedupe_key = self.normalize_dedupe_text(identity.get(field_name, ""))
                if dedupe_key:
                    self.existing_dedupe_key_set.add(dedupe_key)
        self.alibaba_collector.set_existing_lead_identity_list(identity_list)

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        try:
            self.task_event_callback(event_type, level, message)
        except Exception:
            logger.warning("AI web search task event callback failed")

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        return self.collect_from_alibaba_1688(industry, keywords, collect_limit)

    def collect_from_alibaba_1688(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        self.last_collect_diagnostic = ""
        self.emit_task_event(
            "collecting",
            "info",
            "AI 1688搜企已切换为1688站内真实采集：DeepSeek只做候选清洗/品类判断，不作为搜索源、不生成公司名。",
        )
        lead_list = self.alibaba_collector.collect(industry, keywords, collect_limit)
        self.last_collect_diagnostic = getattr(self.alibaba_collector, "last_collect_diagnostic", "")
        if not lead_list:
            self.emit_task_event(
                "collecting",
                "warning",
                self.last_collect_diagnostic
                or "1688精准搜索本次未返回可入库企业；请确认关键词与行业匹配，且1688页面没有登录/验证遮挡。",
            )
            return []
        lead_list = self.refine_alibaba_site_leads_with_ai(industry, keywords, collect_limit, lead_list)
        for lead in lead_list:
            lead.source_type = SOURCE_TYPE_AI_WEB_SEARCH
            if not lead.source_keyword:
                lead.source_keyword = ",".join(keywords[:5]) if keywords else industry
        self.emit_task_event(
            "collecting",
            "info",
            f"1688精准搜索完成：获得 {len(lead_list)} 条候选企业，将先入库并在任务最后补全天眼查联系人和电话。",
        )
        return lead_list

    def refine_alibaba_site_leads_with_ai(
        self,
        industry: str,
        keywords: List[str],
        collect_limit: int,
        lead_list: List[CollectedLeadDTO],
    ) -> List[CollectedLeadDTO]:
        if not lead_list:
            return []
        if not self.ai_service.is_enabled():
            self.emit_task_event(
                "collecting",
                "info",
                "DeepSeek未启用，已跳过AI清洗；本轮公司名全部来自1688站内真实页面。",
            )
            return lead_list

        card_list = self.build_alibaba_site_ai_card_list(lead_list)
        if not card_list:
            return lead_list

        source_keyword = ",".join(keywords[:5]) if keywords else industry
        try:
            ai_result = self.ai_service.analyze_1688_snapshot(
                industry=industry,
                source_keyword=source_keyword,
                page_url="1688-site-search://collected-candidates",
                page_title="1688站内搜索已采集候选",
                page_text="\n".join(card.get("text", "") for card in card_list),
                card_list=card_list,
                collect_limit=max(1, min(max(len(lead_list), collect_limit), 80)),
                source_type=SOURCE_TYPE_AI_WEB_SEARCH,
            )
        except Exception as ex:
            logger.exception("DeepSeek 1688 candidate cleanup failed, error=%s", ex)
            self.emit_task_event(
                "collecting",
                "warning",
                f"DeepSeek候选清洗失败，已保留1688真实采集结果继续；原因：{ex}",
            )
            return lead_list

        ai_match_map = self.build_ai_alibaba_lead_match_map(ai_result.lead_list, lead_list)
        if not ai_match_map:
            self.emit_task_event(
                "collecting",
                "warning",
                "DeepSeek本轮没有返回可精确匹配1688真实公司名的结果；已保留1688真实采集结果，不采用AI生成企业。",
            )
            return lead_list

        cleaned_count = 0
        for lead in lead_list:
            match_key = clean_company_name_text(lead.suspected_company_name)
            ai_lead = ai_match_map.get(match_key)
            if ai_lead is None:
                continue
            self.apply_ai_cleanup_to_alibaba_lead(lead, ai_lead)
            cleaned_count += 1

        self.emit_task_event(
            "collecting",
            "info",
            f"DeepSeek 1688候选清洗完成：只匹配1688真实公司名 {cleaned_count}/{len(lead_list)} 条；未匹配项保留原始1688结果。",
        )
        return lead_list

    def build_alibaba_site_ai_card_list(self, lead_list: List[CollectedLeadDTO]) -> List[Dict]:
        card_list = []
        for index, lead in enumerate(lead_list[:80], start=1):
            field_list = [
                f"序号：{index}",
                f"公司名：{lead.suspected_company_name}",
                f"产品/标题：{lead.product_name}",
                f"联系人：{lead.contact_name}",
                f"电话：{lead.phone if has_public_phone_text(lead.phone) else ''}",
                f"电话来源：{lead.phone_source}",
                f"地址/地区：{lead.registered_address or lead.region_text}",
                f"经营范围：{lead.business_scope}",
                f"来源关键词：{lead.source_keyword}",
            ]
            card_list.append(
                {
                    "text": self.clean_text("；".join(field for field in field_list if field and not field.endswith("："))),
                    "href": lead.profile_url or lead.shop_url,
                }
            )
        return card_list

    def build_ai_alibaba_lead_match_map(
        self,
        ai_lead_list: List[CollectedLeadDTO],
        original_lead_list: List[CollectedLeadDTO],
    ) -> Dict[str, CollectedLeadDTO]:
        original_name_set = {
            clean_company_name_text(lead.suspected_company_name)
            for lead in original_lead_list
            if clean_company_name_text(lead.suspected_company_name)
        }
        result_map = {}
        for ai_lead in ai_lead_list:
            match_key = clean_company_name_text(ai_lead.suspected_company_name)
            if not match_key or match_key not in original_name_set or match_key in result_map:
                continue
            result_map[match_key] = ai_lead
        return result_map

    def apply_ai_cleanup_to_alibaba_lead(self, target: CollectedLeadDTO, ai_lead: CollectedLeadDTO) -> None:
        visible_text = self.clean_text(
            " ".join(
                [
                    target.suspected_company_name,
                    target.product_name,
                    target.contact_name,
                    target.phone,
                    target.phone_source,
                    target.registered_address,
                    target.business_scope,
                    target.region_text,
                    target.source_keyword,
                ]
            )
        )
        if ai_lead.product_name and (not target.product_name or self.is_visible_ai_field(ai_lead.product_name, visible_text)):
            target.product_name = ai_lead.product_name[:120]
        if ai_lead.business_scope and not target.business_scope:
            target.business_scope = ai_lead.business_scope[:500]
        if ai_lead.registered_address and not target.registered_address:
            target.registered_address = ai_lead.registered_address[:300]
        if is_valid_contact_name(ai_lead.contact_name) and (
            not is_valid_contact_name(target.contact_name) or self.is_visible_ai_field(ai_lead.contact_name, visible_text)
        ):
            target.contact_name = ai_lead.contact_name
        if has_public_phone_text(ai_lead.phone):
            merged_phone = self.merge_phone(target.phone, ai_lead.phone)
            if has_public_phone_text(merged_phone):
                target.phone = merged_phone
                target.phone_source = self.merge_text(
                    target.phone_source,
                    ai_lead.phone_source or "DeepSeek清洗1688公开字段",
                )[:200]
        if ai_lead.risk_tag and not target.risk_tag:
            target.risk_tag = ai_lead.risk_tag[:200]
        target.region_text = self.merge_text(target.region_text, ai_lead.region_text)[:3000]

    def is_visible_ai_field(self, value: str, visible_text: str) -> bool:
        clean_value = self.clean_text(value)
        if not clean_value:
            return False
        return clean_value in visible_text or clean_value.replace(" ", "") in visible_text.replace(" ", "")

    def merge_phone(self, left_phone: str, right_phone: str) -> str:
        return merge_public_phone_text(left_phone, right_phone, include_service=True)

    def collect_from_public_web_search(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        self.last_collect_diagnostic = ""
        if not self.ai_service.is_enabled():
            raise RuntimeError("DeepSeek AI未启用或未配置Key，无法执行AI 1688索引搜企。")
        raw_query_list = self.build_search_query_list(industry, keywords)
        query_list = self.limit_search_query_list(raw_query_list, collect_limit)
        candidate_buffer_limit = self.get_candidate_buffer_limit(collect_limit)
        if len(query_list) < len(raw_query_list):
            self.emit_task_event(
                "collecting",
                "info",
                f"AI 1688索引已按采集数量收敛搜索范围：从 {len(raw_query_list)} 组关键词优先执行 {len(query_list)} 组。",
            )
        candidate_document_target = self.get_candidate_document_target_count(collect_limit)
        self.emit_task_event(
            "collecting",
            "info",
            f"AI 1688索引搜企已启动：将只查询搜索引擎已收录的1688公开摘要，不进入1688页面；"
            f"本轮会先扩大候选摘要池到约 {candidate_document_target} 个，再筛选入库。",
        )
        document_list = self.collect_public_document_list(query_list, collect_limit, candidate_document_target)
        if not document_list:
            self.last_collect_diagnostic = (
                "AI 1688索引搜索未获得可识别的1688公开结果；可以换更具体的品类词，"
                "或配置稳定的搜索API提升索引命中率。"
            )
            self.emit_task_event("collecting", "warning", self.last_collect_diagnostic)
            return []

        source_keyword = ",".join(keywords[:5]) if keywords else industry
        rule_lead_list = self.extract_rule_leads_from_documents(
            industry=industry,
            source_keyword=source_keyword,
            document_list=document_list,
            collect_limit=candidate_buffer_limit,
        )
        try:
            ai_result = self.ai_service.analyze_public_web_documents(
                industry=industry,
                source_keyword=source_keyword,
                document_list=[
                    {
                        "title": document.title,
                        "url": document.url,
                        "snippet": document.snippet,
                        "text": document.text,
                    }
                    for document in document_list
                ],
                collect_limit=candidate_buffer_limit,
                source_type=SOURCE_TYPE_AI_WEB_SEARCH,
            )
            ai_lead_list = ai_result.lead_list
        except Exception as ex:
            logger.exception("AI web document recognition failed, error=%s", ex)
            self.emit_task_event("collecting", "warning", f"AI 1688索引识别失败，已使用规则抽取结果继续；原因：{ex}")
            ai_lead_list = []
        primary_lead_list = self.dedupe_lead_list(rule_lead_list + ai_lead_list, candidate_buffer_limit)
        fallback_lead_list = self.extract_fallback_leads_from_documents(
            industry=industry,
            source_keyword=source_keyword,
            document_list=document_list,
            collect_limit=candidate_buffer_limit,
        )
        primary_key_set = {
            clean_company_name_text(lead.suspected_company_name)
            for lead in primary_lead_list
            if clean_company_name_text(lead.suspected_company_name)
        }
        fallback_added_count = sum(
            1
            for lead in fallback_lead_list
            if clean_company_name_text(lead.suspected_company_name)
            and clean_company_name_text(lead.suspected_company_name) not in primary_key_set
        )
        lead_list = self.dedupe_lead_list(primary_lead_list + fallback_lead_list, candidate_buffer_limit)
        if fallback_added_count > 0:
            self.emit_task_event(
                "collecting",
                "warning",
                f"规则/AI识别候选不足，已启用可信公开结果兜底识别 {fallback_added_count} 条目标企业待补全候选。",
            )
        self.emit_task_event(
            "collecting",
            "info",
            f"AI 1688索引识别完成：从 {len(document_list)} 个1688公开摘要中识别 {len(lead_list)} 条候选企业"
            f"（规则 {len(rule_lead_list)} 条，AI {len(ai_lead_list)} 条，兜底 {len(fallback_lead_list)} 条）。",
        )
        if not lead_list:
            self.last_collect_diagnostic = (
                "AI 1688索引未产生候选企业：搜索结果摘要里没有同时满足企业名、广东信号、"
                "品类证据和供应商意图的1688结果。"
            )
            self.emit_task_event(
                "collecting",
                "warning",
                self.last_collect_diagnostic,
            )
            return []
        self.emit_task_event(
            "collecting",
            "info",
            "AI 1688索引基础候选已形成；系统将先入库，任务最后再尝试用天眼查公开页补全电话、联系人和法人。",
        )
        result_list = []
        partial_result_list = []
        skip_count_map = {
            "restricted": 0,
            "non_guangdong": 0,
            "irrelevant": 0,
            "suspicious_name": 0,
            "missing_phone": 0,
            "missing_contact": 0,
            "duplicate": 0,
        }
        for lead in lead_list:
            lead.suspected_company_name = clean_company_name_text(lead.suspected_company_name)
            disqualified_reason = get_disqualified_lead_reason(lead)
            if disqualified_reason:
                skip_count_map["restricted"] += 1
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过非正常状态线索：{lead.suspected_company_name}，原因：{disqualified_reason}",
                )
                continue
            if not self.is_valid_rule_company_name(lead.suspected_company_name):
                skip_count_map["suspicious_name"] += 1
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过低置信企业名：{lead.suspected_company_name}",
                )
                continue
            if not self.is_ai_web_guangdong_candidate(lead):
                skip_count_map["non_guangdong"] += 1
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过非广东候选：{lead.suspected_company_name}",
                )
                continue
            if not self.is_ai_web_lead_relevant(lead):
                skip_count_map["irrelevant"] += 1
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过非目标品类线索：{lead.suspected_company_name}",
                )
                continue
            if self.is_ai_web_company_name_suspicious(lead.suspected_company_name):
                skip_count_map["suspicious_name"] += 1
                self.emit_task_event(
                    "collecting",
                    "info",
                    f"已跳过疑似目录页假企业名：{lead.suspected_company_name}",
                )
                continue
            if not has_public_phone_text(lead.phone):
                skip_count_map["missing_phone"] += 1
            if not is_valid_contact_name(lead.contact_name) and is_valid_contact_name(lead.legal_person):
                lead.contact_name = lead.legal_person
            if not is_valid_contact_name(lead.contact_name):
                skip_count_map["missing_contact"] += 1
            if self.is_existing_lead(lead):
                skip_count_map["duplicate"] += 1
                continue
            if not self.is_ai_web_complete_contact_lead(lead):
                partial_result_list.append(self.prepare_ai_web_partial_lead(lead))
                continue
            self.remember_lead(lead)
            result_list.append(lead)
            if len(result_list) >= collect_limit:
                break
        if len(result_list) < collect_limit and partial_result_list:
            partial_added_count = 0
            for partial_lead in partial_result_list:
                if len(result_list) >= collect_limit:
                    break
                if self.is_existing_lead(partial_lead):
                    continue
                self.remember_lead(partial_lead)
                result_list.append(partial_lead)
                partial_added_count += 1
            if partial_added_count > 0:
                self.emit_task_event(
                    "collecting",
                    "warning",
                    f"本轮完整联系人/电话线索不足，已先入库 {partial_added_count} 条目标企业待补全候选。",
                )
        if not result_list:
            self.last_collect_diagnostic = (
                "AI 1688索引候选企业未进入线索库："
                f"非正常状态 {skip_count_map['restricted']} 条，"
                f"非广东 {skip_count_map['non_guangdong']} 条，"
                f"非目标品类 {skip_count_map['irrelevant']} 条，"
                f"疑似假名 {skip_count_map['suspicious_name']} 条，"
                f"无公开电话 {skip_count_map['missing_phone']} 条，"
                f"无可信联系人/法人 {skip_count_map['missing_contact']} 条，"
                f"重复 {skip_count_map['duplicate']} 条。"
            )
            self.emit_task_event(
                "collecting",
                "warning",
                self.last_collect_diagnostic,
            )
        return result_list

    def is_ai_web_guangdong_candidate(self, lead: CollectedLeadDTO) -> bool:
        company_name = clean_company_name_text(lead.suspected_company_name)
        if has_any_token(company_name[:10], NON_GUANGDONG_REGION_PREFIX_LIST):
            return False
        return (
            is_guangdong_text(company_name)
            or is_guangdong_text(lead.registered_address)
            or is_reliable_guangdong_address(lead.registered_address)
            or is_guangdong_text(lead.region_text[:800])
        )

    def is_ai_web_complete_contact_lead(self, lead: CollectedLeadDTO) -> bool:
        return has_public_phone_text(lead.phone) and is_valid_contact_name(lead.contact_name)

    def prepare_ai_web_partial_lead(self, lead: CollectedLeadDTO) -> CollectedLeadDTO:
        if not has_public_phone_text(lead.phone):
            lead.phone = ""
            lead.phone_source = "待补全：公开页和天眼查公开页本轮未见电话"
        if not is_valid_contact_name(lead.contact_name):
            lead.contact_name = ""
        marker = "待补全：缺少公开电话或联系人"
        if marker not in (lead.risk_tag or ""):
            lead.risk_tag = "；".join([value for value in [lead.risk_tag, marker] if value])[:128]
        return lead

    def get_candidate_buffer_limit(self, collect_limit: int) -> int:
        clean_limit = max(1, int(collect_limit or 1))
        return min(max(clean_limit * 4, clean_limit + 15), 80)

    def get_candidate_document_target_count(self, collect_limit: int) -> int:
        clean_limit = max(1, int(collect_limit or 1))
        return min(max(clean_limit * 4, clean_limit + 15, 18), 80)

    def limit_search_query_list(self, query_list: List[str], collect_limit: int) -> List[str]:
        clean_limit = max(1, int(collect_limit or 1))
        max_query_count = min(PUBLIC_WEB_SEARCH_KEYWORD_LIMIT, max(12, clean_limit * 5))
        return query_list[:max_query_count]

    def build_search_query_list(self, industry: str, keywords: List[str]) -> List[str]:
        base_keyword_list = self.build_ai_web_search_base_keyword_list(industry, keywords)
        query_list = []

        def append_1688_query(clean_keyword: str, *extra_token_list: str) -> None:
            token_list = ["site:1688.com", clean_keyword]
            for extra_token in extra_token_list:
                clean_extra_token = self.clean_text(extra_token)
                if not clean_extra_token:
                    continue
                if clean_extra_token in clean_keyword or clean_extra_token in token_list:
                    continue
                token_list.append(clean_extra_token)
            query_list.append(" ".join(token_list))

        for keyword in base_keyword_list:
            clean_keyword = self.clean_text(keyword)
            if not clean_keyword:
                continue
            core_keyword = self.build_ai_web_query_core_keyword(clean_keyword)
            has_location = self.has_guangdong_location_token(clean_keyword)
            if has_location:
                search_keyword = clean_keyword
                core_search_keyword = core_keyword
            else:
                search_keyword = f"广州 {clean_keyword}".strip()
                core_search_keyword = f"广州 {core_keyword}".strip()
            append_1688_query(search_keyword)
            if core_keyword != clean_keyword:
                append_1688_query(core_search_keyword)
            append_1688_query(search_keyword, "工厂", "供应商")
            append_1688_query(search_keyword, "厂家", "批发")
            append_1688_query(search_keyword, "OEM", "加工")
            append_1688_query(search_keyword, "制造商")
            append_1688_query(search_keyword, "公司")
            if not has_location:
                for city_name in ("广州", "东莞", "佛山", "广东", "深圳", "中山"):
                    append_1688_query(f"{city_name} {clean_keyword}".strip(), "工厂", "1688")
                    if core_keyword != clean_keyword:
                        append_1688_query(f"{city_name} {core_keyword}".strip(), "1688")
        return self.dedupe_text_list(query_list)[:PUBLIC_WEB_SEARCH_KEYWORD_LIMIT]

    def build_ai_web_query_core_keyword(self, keyword: str) -> str:
        clean_keyword = self.clean_text(keyword)
        reduced_keyword = clean_keyword
        for token in sorted(set(GENERIC_1688_KEYWORD_TOKEN_LIST + BUSINESS_KEYWORD_LIST), key=len, reverse=True):
            if token:
                reduced_keyword = re.sub(re.escape(token), " ", reduced_keyword, flags=re.IGNORECASE)
        reduced_keyword = self.clean_text(re.sub(r"[\s,，、;；/\\|_+\-]+", " ", reduced_keyword))
        return reduced_keyword if len(reduced_keyword) >= 2 else clean_keyword

    def build_ai_web_search_base_keyword_list(self, industry: str, keywords: List[str]) -> List[str]:
        raw_keyword_list = []
        for keyword_text in keywords or [industry]:
            for keyword in split_public_search_keyword(keyword_text):
                clean_keyword = self.clean_text(keyword)
                if clean_keyword:
                    raw_keyword_list.append(clean_keyword)
        if not raw_keyword_list and industry:
            raw_keyword_list.append(industry)

        result_list = []
        broad_keyword_seen = False
        broad_keyword_tail_list = []
        industry_default_list = INDUSTRY_PUBLIC_SEARCH_KEYWORD_MAP.get(industry, [])
        for keyword in raw_keyword_list[:12]:
            if self.is_ai_web_broad_category_keyword(keyword, industry):
                broad_keyword_seen = True
                append_unique_text(broad_keyword_tail_list, keyword)
                continue
            append_unique_text(result_list, keyword)

        if broad_keyword_seen or not result_list:
            for default_keyword in industry_default_list:
                append_unique_text(result_list, default_keyword)
        for default_keyword in industry_default_list:
            append_unique_text(result_list, default_keyword)
        for keyword in broad_keyword_tail_list:
            append_unique_text(result_list, keyword)
        return result_list[:24]

    def is_ai_web_broad_category_keyword(self, keyword: str, industry: str) -> bool:
        clean_keyword = self.clean_text(keyword)
        if not clean_keyword:
            return True
        specific_token_list = AI_WEB_SPECIFIC_CATEGORY_KEYWORD_MAP.get(industry, [])
        if has_any_token(clean_keyword, specific_token_list):
            return False
        broad_token_list = (
            INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [])
            + GENERIC_1688_KEYWORD_TOKEN_LIST
            + BUSINESS_KEYWORD_LIST
            + ["公司", "企业", "供应商", "厂家", "广东", "广州", "深圳", "东莞", "佛山", "中山"]
        )
        reduced_keyword = clean_keyword
        for token in sorted(set(broad_token_list), key=len, reverse=True):
            if token:
                reduced_keyword = re.sub(re.escape(token), " ", reduced_keyword, flags=re.IGNORECASE)
        reduced_keyword = re.sub(r"[\s,，、;；/\\|_+\-]+", "", reduced_keyword)
        return len(reduced_keyword) <= 1

    def has_guangdong_location_token(self, text: str) -> bool:
        return has_any_token(
            text,
            [
                "广东",
                "广州",
                "深圳",
                "东莞",
                "佛山",
                "中山",
                "珠海",
                "惠州",
                "汕头",
                "江门",
                "湛江",
                "肇庆",
                "清远",
                "揭阳",
                "潮州",
            ],
        )

    def collect_public_document_list(
        self,
        query_list: List[str],
        collect_limit: int,
        target_document_count: Optional[int] = None,
    ) -> List[PublicPageDocument]:
        document_list: List[PublicPageDocument] = []
        seen_url_set = set()
        search_result_count = 0
        skipped_blocked_count = 0
        skipped_low_value_count = 0
        target_count = max(1, int(target_document_count or self.get_candidate_document_target_count(collect_limit)))
        configured_max_count = max(1, int(self.config.web_search_max_page_fetch_count or 1))
        max_document_count = min(max(configured_max_count, target_count), 80)
        for query in query_list:
            if len(document_list) >= max_document_count:
                break
            self.emit_task_event("collecting", "info", f"正在搜索1688公开索引结果：{query}")
            try:
                result_list = self.web_search_service.search(query, self.config.web_search_max_results_per_query)
            except Exception as ex:
                logger.exception("AI web search failed, query=%s, error=%s", query, ex)
                self.emit_task_event("collecting", "warning", f"1688索引搜索源全部不可用，已跳过该关键词：{query}；原因：{ex}")
                continue
            if not result_list:
                self.emit_task_event("collecting", "info", f"该关键词未返回可用1688索引结果，已继续下一组：{query}")
                continue
            for result in result_list:
                search_result_count += 1
                if len(document_list) >= max_document_count:
                    break
                if not self.is_1688_index_result(result):
                    skipped_low_value_count += 1
                    continue
                key = result.url.split("#")[0].rstrip("/")
                if key in seen_url_set:
                    continue
                seen_url_set.add(key)
                industry_hint = self.infer_industry_from_query(query)
                preview_document = PublicPageDocument(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    text=f"{result.title} {result.snippet}",
                    source_query=query,
                )
                document = preview_document
                if self.is_ai_web_blocked_document(document):
                    skipped_blocked_count += 1
                    continue
                if not self.is_ai_web_candidate_document(document, industry_hint):
                    skipped_low_value_count += 1
                    continue
                document_list.append(document)
                if self.has_enough_candidate_company_documents(document_list, target_count):
                    break
            if self.has_enough_candidate_company_documents(document_list, target_count):
                break
            self.web_search_service.sleep_between_requests()
        self.emit_task_event(
            "collecting",
            "info",
            f"AI 1688索引搜索结果过滤：原始结果 {search_result_count} 个，保留候选摘要 {len(document_list)} 个，"
            f"目标候选摘要约 {target_count} 个，跳过验证/受限摘要 {skipped_blocked_count} 个，"
            f"跳过非1688或低相关结果 {skipped_low_value_count} 个。",
        )
        return document_list

    @staticmethod
    def is_1688_index_result_url(url: str) -> bool:
        if not url:
            return False
        parsed_url = urlparse(url)
        host = (parsed_url.netloc or "").lower()
        return host == "1688.com" or host.endswith(".1688.com")

    def is_1688_index_result(self, result: WebSearchResult) -> bool:
        if self.is_1688_index_result_url(result.url):
            return True
        preview_text = self.clean_text(" ".join([result.title, result.snippet, result.url]))
        if not has_any_token(preview_text, ["1688", "阿里巴巴", "alibaba"]):
            return False
        return not has_any_token(preview_text, ["爱企查", "企查查", "天眼查", "启信宝"])

    def should_use_search_result_preview(self, document: PublicPageDocument, industry: str) -> bool:
        preview_text = self.clean_text(" ".join([document.title, document.snippet]))
        if not preview_text:
            return False
        if "sogou.com/link" in (document.url or "").lower():
            return True
        if not COMPANY_NAME_PATTERN.search(preview_text):
            return False
        return self.is_ai_web_candidate_document(document, industry)

    def has_enough_candidate_company_documents(
        self,
        document_list: List[PublicPageDocument],
        collect_limit: int,
    ) -> bool:
        target_count = max(1, int(collect_limit or 1))
        company_name_set = set()
        for document in document_list:
            searchable_text = self.clean_text(" ".join([document.title, document.snippet, document.text[:3000]]))
            for company_name in self.extract_company_name_list_from_text(searchable_text):
                key = clean_company_name_text(company_name)
                if not key or self.is_ai_web_platform_company_name(key):
                    continue
                company_name_set.add(key)
                if len(company_name_set) >= target_count:
                    return True
        return False

    def is_ai_web_blocked_document(self, document: PublicPageDocument) -> bool:
        text = self.clean_text(" ".join([document.title, document.snippet, document.text[:1000]]))
        return has_any_token(
            text,
            [
                "验证码验证",
                "正在验证",
                "安全验证",
                "请完成验证",
                "身份验证",
                "访问受限",
                "拖动滑块",
                "访问过于频繁",
                "人机验证",
            ],
        )

    def is_ai_web_candidate_document(self, document: PublicPageDocument, industry: str = "") -> bool:
        url_text = (document.url or "").lower()
        preview_text = self.clean_text(" ".join([document.title, document.snippet, document.text[:1800]]))
        if not preview_text:
            return False
        is_search_result_redirect = "sogou.com/link" in url_text or "e.so.com/search/eclk" in url_text
        if (
            has_any_token(url_text, AI_WEB_LOW_VALUE_HOST_TOKEN_LIST)
            and not is_search_result_redirect
        ) or has_any_token(preview_text, AI_WEB_LOW_VALUE_TEXT_TOKEN_LIST):
            return False
        if get_disqualified_text_reason(preview_text):
            return False
        if not COMPANY_NAME_PATTERN.search(preview_text):
            return False
        raw_company_name_list = [
            clean_company_name_text(match.group(1))
            for match in COMPANY_NAME_PATTERN.finditer(preview_text)
            if clean_company_name_text(match.group(1))
        ]
        if raw_company_name_list and all(self.is_ai_web_platform_company_name(name) for name in raw_company_name_list):
            return False
        company_name_list = [name for name in raw_company_name_list if self.is_valid_rule_company_name(name)]
        if not company_name_list:
            return False
        if (
            industry
            and company_name_list
            and all(self.has_ai_web_non_target_company_bias(industry, name) for name in company_name_list)
        ):
            return False
        if company_name_list and all(has_any_token(clean_company_name_text(name)[:10], NON_GUANGDONG_REGION_PREFIX_LIST) for name in company_name_list):
            return False
        if company_name_list and all(self.is_ai_web_platform_company_name(name) for name in company_name_list):
            return False
        if (
            company_name_list
            and all(has_any_token(clean_company_name_text(name), PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST) for name in company_name_list)
            and not self.has_ai_web_category_evidence(industry, preview_text)
        ):
            return False
        trusted_text = self.build_ai_web_document_evidence_text(document)
        if self.is_ai_web_trusted_supplier_document(document):
            return self.has_ai_web_supplier_intent(trusted_text) and self.has_ai_web_category_evidence(industry, trusted_text)
        return self.has_ai_web_supplier_intent(preview_text) and self.has_ai_web_category_evidence(industry, preview_text)

    def infer_industry_from_query(self, query: str) -> str:
        clean_query = self.clean_text(query)
        for industry, token_list in INDUSTRY_RELEVANCE_KEYWORD_MAP.items():
            if has_any_token(clean_query, token_list) or industry in clean_query:
                return industry
        return ""

    def is_ai_web_trusted_supplier_document(self, document: PublicPageDocument) -> bool:
        url_text = (document.url or "").lower()
        if has_any_token(url_text, AI_WEB_TRUSTED_SUPPLIER_HOST_TOKEN_LIST):
            return True
        source_query = (document.source_query or "").lower()
        preview_text = self.clean_text(" ".join([document.title, document.snippet]))
        return "site:1688.com" in source_query and has_any_token(preview_text, ["1688", "阿里巴巴", "alibaba"])

    def build_ai_web_document_evidence_text(self, document: PublicPageDocument) -> str:
        base_text = self.clean_text(" ".join([document.title, document.snippet, document.text[:1800]]))
        return base_text

    def extract_rule_leads_from_documents(
        self,
        industry: str,
        source_keyword: str,
        document_list: List[PublicPageDocument],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        lead_list: List[CollectedLeadDTO] = []
        dedupe_set = set()
        for document in document_list:
            if len(lead_list) >= collect_limit:
                break
            searchable_text = self.clean_text(" ".join([document.title, document.snippet, document.text[:12000]]))
            document_hint_text = self.build_ai_web_document_evidence_text(document)
            phone_frequency_map = self.build_phone_frequency_map(searchable_text)
            company_candidate_list = self.extract_rule_company_candidate_list_from_text(
                searchable_text,
                industry,
                source_keyword,
                document_hint_text,
            )
            for company_name, match_context, contact_context in company_candidate_list:
                if len(lead_list) >= collect_limit:
                    break
                key = clean_company_name_text(company_name)
                if not key or key in dedupe_set:
                    continue
                dedupe_set.add(key)
                phone = self.extract_public_phone(contact_context, phone_frequency_map)
                if not phone:
                    phone = self.extract_public_phone(match_context, phone_frequency_map)
                evidence_text = self.clean_text(" ".join([document.title, document.snippet, match_context]))
                contact_name = extract_strict_contact_name_by_pattern(contact_context)
                if not contact_name:
                    contact_name = extract_strict_contact_name_by_pattern(match_context)
                lead_list.append(
                    CollectedLeadDTO(
                        source_type=SOURCE_TYPE_AI_WEB_SEARCH,
                        source_keyword=source_keyword,
                        industry=industry,
                        suspected_company_name=key,
                        product_name=self.pick_rule_product_name(document.title, match_context, industry, source_keyword),
                        contact_name=contact_name,
                        phone=phone,
                        phone_source="全网公开页可见字段" if phone else "",
                        registered_address=self.extract_address_text(match_context),
                        region_text=evidence_text[:3000],
                        website_url=document.url,
                        profile_url=document.url,
                        is_enterprise_verified=True,
                        commercial_keyword_count=1,
                    )
                )
        return lead_list

    def extract_fallback_leads_from_documents(
        self,
        industry: str,
        source_keyword: str,
        document_list: List[PublicPageDocument],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        lead_list: List[CollectedLeadDTO] = []
        dedupe_set = set()
        for document in document_list:
            if len(lead_list) >= collect_limit:
                break
            searchable_text = self.clean_text(" ".join([document.title, document.snippet, document.text[:8000]]))
            if not searchable_text:
                continue
            document_hint_text = self.build_ai_web_document_evidence_text(document)
            phone_frequency_map = self.build_phone_frequency_map(searchable_text)
            for match in COMPANY_NAME_PATTERN.finditer(searchable_text):
                if len(lead_list) >= collect_limit:
                    break
                company_name = clean_company_name_text(match.group(1))
                if not self.is_valid_rule_company_name(company_name):
                    continue
                key = clean_company_name_text(company_name)
                if not key or key in dedupe_set:
                    continue
                match_context = self.extract_rule_match_context(searchable_text, match.start(), match.end())
                contact_context = self.extract_rule_contact_context(searchable_text, match.start(), match.end())
                if not self.is_ai_web_fallback_company_relevant(
                    company_name=key,
                    context_text=match_context,
                    industry=industry,
                    source_keyword=source_keyword,
                    document_text=searchable_text,
                    document_hint_text=document_hint_text,
                ):
                    continue
                dedupe_set.add(key)
                phone = self.extract_public_phone(contact_context, phone_frequency_map)
                if not phone:
                    phone = self.extract_public_phone(match_context, phone_frequency_map)
                contact_name = extract_strict_contact_name_by_pattern(contact_context)
                if not contact_name:
                    contact_name = extract_strict_contact_name_by_pattern(match_context)
                evidence_text = self.clean_text(" ".join([document.title, document.snippet, match_context]))
                company_status = extract_public_company_status_text(match_context)
                lead_list.append(
                    CollectedLeadDTO(
                        source_type=SOURCE_TYPE_AI_WEB_SEARCH,
                        source_keyword=source_keyword,
                        industry=industry,
                        suspected_company_name=key,
                        product_name=self.pick_rule_product_name(document.title, match_context, industry, source_keyword),
                        contact_name=contact_name,
                        phone=phone,
                        phone_source="全网公开页可见字段" if phone else "待补全：公开页本轮未见电话",
                        company_status=company_status,
                        business_scope=extract_public_labeled_business_text(match_context),
                        registered_address=self.extract_address_text(match_context) or self.extract_address_text(searchable_text[:2400]),
                        risk_tag="待补全：可信公开结果兜底识别",
                        region_text=evidence_text[:3000],
                        website_url=document.url,
                        profile_url=document.url,
                        is_enterprise_verified=True,
                        commercial_keyword_count=1,
                    )
                )
        return lead_list

    def is_ai_web_fallback_company_relevant(
        self,
        company_name: str,
        context_text: str,
        industry: str,
        source_keyword: str,
        document_text: str,
        document_hint_text: str,
    ) -> bool:
        clean_company_name = clean_company_name_text(company_name)
        clean_context = self.clean_text(context_text)
        clean_document_text = self.clean_text(document_text)
        clean_document_hint = self.clean_text(document_hint_text)
        if not clean_context:
            return False
        if self.is_ai_web_platform_company_name(clean_company_name):
            return False
        if self.has_ai_web_non_target_company_bias(industry, clean_company_name):
            return False
        if self.is_rule_noise_context(clean_company_name, clean_context):
            return False
        if get_disqualified_text_reason(" ".join([clean_company_name, clean_context, clean_document_text[:1200]])):
            return False
        if not (
            is_guangdong_text(clean_company_name)
            or is_guangdong_text(clean_context)
            or is_guangdong_text(clean_document_text[:1800])
        ):
            return False

        strong_token_list = INDUSTRY_STRONG_RELEVANCE_KEYWORD_MAP.get(
            industry,
            INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry] if industry else []),
        )
        evidence_text = self.clean_text(" ".join([clean_company_name, clean_context, clean_document_hint]))
        local_evidence_text = self.clean_text(" ".join([clean_company_name, clean_context, clean_document_text[:1800]]))
        if not self.has_ai_web_category_evidence(industry, evidence_text):
            return False
        if not self.has_ai_web_supplier_intent(evidence_text, clean_company_name):
            return False
        if has_any_token(clean_company_name, PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST):
            if not has_any_token(local_evidence_text, strong_token_list):
                return False

        keyword_token_list = self.build_ai_web_keyword_token_list(source_keyword, industry)
        if keyword_token_list and has_any_token(local_evidence_text.upper(), [token.upper() for token in keyword_token_list]):
            return True
        if has_any_token(local_evidence_text, strong_token_list):
            return True
        return not has_any_token(clean_company_name, PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST)

    def extract_company_name_list_from_text(self, text: str) -> List[str]:
        return [
            company_name
            for company_name, _, _ in self.extract_rule_company_candidate_list_from_text(text, "", "", "")
        ]

    def extract_rule_company_candidate_list_from_text(
        self,
        text: str,
        industry: str,
        source_keyword: str,
        document_hint_text: str = "",
    ) -> List[Tuple[str, str, str]]:
        result_list = []
        seen_set = set()
        for match in COMPANY_NAME_PATTERN.finditer(text or ""):
            company_name = clean_company_name_text(match.group(1))
            if not self.is_valid_rule_company_name(company_name):
                continue
            match_context = self.extract_rule_match_context(text or "", match.start(), match.end())
            contact_context = self.extract_rule_contact_context(text or "", match.start(), match.end())
            if industry and not self.is_rule_company_context_relevant(
                company_name,
                match_context,
                industry,
                source_keyword,
                document_hint_text,
            ):
                continue
            key = clean_company_name_text(company_name)
            if key in seen_set:
                continue
            seen_set.add(key)
            result_list.append((key, match_context, contact_context))
        return result_list

    def extract_rule_match_context(self, text: str, start_index: int, end_index: int) -> str:
        return self.extract_rule_context(text, start_index, end_index, 900)

    def extract_rule_contact_context(self, text: str, start_index: int, end_index: int) -> str:
        return self.extract_rule_context(text, start_index, end_index, 260)

    def extract_rule_context(self, text: str, start_index: int, end_index: int, radius: int) -> str:
        return self.clean_text(text[max(0, start_index - radius) : min(len(text), end_index + radius)])

    def is_rule_company_context_relevant(
        self,
        company_name: str,
        context_text: str,
        industry: str,
        source_keyword: str,
        document_hint_text: str = "",
    ) -> bool:
        clean_company_name = clean_company_name_text(company_name)
        clean_context = self.clean_text(context_text)
        clean_document_hint = self.clean_text(document_hint_text)
        if not clean_context:
            return False
        if self.is_rule_noise_context(clean_company_name, clean_context):
            return False
        inactive_status = extract_public_company_status_text(clean_context)
        if is_inactive_company_status(inactive_status) or has_inactive_company_banner_text(clean_context):
            return False

        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry] if industry else [])
        strong_token_list = INDUSTRY_STRONG_RELEVANCE_KEYWORD_MAP.get(industry, industry_token_list)
        merged_text = " ".join([clean_company_name, clean_context, clean_document_hint])
        web_evidence_text = " ".join([clean_company_name, clean_context, clean_document_hint])
        if self.is_ai_web_platform_company_name(clean_company_name):
            return False
        if self.has_ai_web_non_target_company_bias(industry, clean_company_name):
            return False
        if not self.has_ai_web_category_evidence(industry, web_evidence_text):
            return False
        if not self.has_ai_web_supplier_intent(web_evidence_text, clean_company_name):
            return False
        if not has_any_token(merged_text, industry_token_list):
            return False

        score = 0
        if has_any_token(clean_company_name, industry_token_list):
            score += 3
        if has_any_token(clean_context, strong_token_list):
            score += 3
        elif has_any_token(clean_context, industry_token_list):
            score += 2
        elif has_any_token(clean_document_hint, industry_token_list):
            score += 1
        if has_any_token(clean_document_hint, strong_token_list):
            score += 1
        if has_any_token(merged_text, BUSINESS_KEYWORD_LIST):
            score += 1
        if has_public_phone_text(clean_context):
            score += 1
        if has_any_token(clean_context, ["联系人", "联系电话", "主营", "经营范围", "地址"]):
            score += 1

        keyword_token_list = [
            token
            for token in self.build_ai_web_keyword_token_list(source_keyword, industry)
            if token not in industry_token_list
        ]
        if keyword_token_list:
            merged_upper = merged_text.upper()
            if any(token.upper() in merged_upper for token in keyword_token_list):
                score += 1

        is_weak_company_name = has_any_token(clean_company_name, PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST)
        if is_weak_company_name and not has_any_token(" ".join([clean_context, clean_document_hint]), strong_token_list):
            return False
        return score >= (4 if is_weak_company_name else 2)

    def is_ai_web_platform_company_name(self, company_name: str) -> bool:
        return has_any_token(company_name, AI_WEB_PLATFORM_COMPANY_TOKEN_LIST)

    def has_ai_web_category_evidence(self, industry: str, evidence_text: str) -> bool:
        token_list = AI_WEB_CATEGORY_EVIDENCE_KEYWORD_MAP.get(
            industry,
            INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry] if industry else []),
        )
        return has_any_token(evidence_text, token_list)

    def has_ai_web_non_target_company_bias(self, industry: str, company_name: str) -> bool:
        clean_company_name = clean_company_name_text(company_name)
        if not clean_company_name:
            return True
        return has_any_token(clean_company_name, AI_WEB_NON_TARGET_COMPANY_TOKEN_MAP.get(industry, []))

    def has_ai_web_supplier_intent(self, evidence_text: str, company_name: str = "") -> bool:
        clean_company_name = clean_company_name_text(company_name)
        if clean_company_name.endswith(("工厂", "厂")):
            return True
        return has_any_token(evidence_text, AI_WEB_SUPPLIER_INTENT_TOKEN_LIST)

    def is_ai_web_company_name_suspicious(self, company_name: str) -> bool:
        clean_name = clean_company_name_text(company_name)
        if not clean_name:
            return True
        if self.is_ai_web_platform_company_name(clean_name):
            return True
        suspicious_token_list = (
            "名录",
            "黄页",
            "厂家大全",
            "企业名录",
            "采购指南",
            "行业厂",
            "生产厂家",
            "生产厂",
            "服装批发商",
            "供应商拥有",
            "中国制造网",
            "马可波罗",
            "顺企网",
            "黄页88",
            "爱厂家",
            "许多",
            "自己的工厂",
            "专用机械设备",
            "私营股份有限公司",
        )
        if has_any_token(clean_name, suspicious_token_list):
            return True
        city_token_list = [
            "广州",
            "深圳",
            "东莞",
            "佛山",
            "中山",
            "珠海",
            "惠州",
            "汕头",
            "江门",
            "湛江",
            "肇庆",
            "清远",
            "揭阳",
            "潮州",
        ]
        city_hit_count = sum(clean_name.count(token) for token in city_token_list)
        if city_hit_count > 1:
            return True
        non_guangdong_location_list = [
            "广西",
            "海南",
            "杭州",
            "青岛",
            "上海",
            "北京",
            "苏州",
            "南京",
            "温州",
            "宁波",
            "泉州",
            "厦门",
            "成都",
            "武汉",
            "长沙",
            "郑州",
        ]
        if has_any_token(clean_name[:8], non_guangdong_location_list):
            return True
        return False

    def is_rule_noise_context(self, company_name: str, context_text: str) -> bool:
        noise_token_list = (
            "政府门户网站",
            "人民政府",
            "政府信息公开",
            "政务服务",
            "主办",
            "承办",
            "技术支持",
            "网站建设",
            "版权所有",
            "ICP备案",
            "网站地图",
            "网站声明",
        )
        if not has_any_token(context_text, noise_token_list):
            return False
        return has_any_token(company_name, PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST) or has_any_token(
            context_text,
            ("技术支持", "网站建设", "政府门户网站", "人民政府"),
        )

    def build_ai_web_keyword_token_list(self, source_keyword: str, industry: str) -> List[str]:
        token_list = []
        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry] if industry else [])
        generic_token_list = (
            GENERIC_1688_KEYWORD_TOKEN_LIST
            + BUSINESS_KEYWORD_LIST
            + ["广东", "广州", "深圳", "东莞", "佛山", "中山", "公司", "联系人", "联系电话", "电话", "供应商"]
        )
        for keyword in split_public_search_keyword(source_keyword):
            clean_keyword = self.clean_text(keyword)
            if not clean_keyword:
                continue
            for token in industry_token_list:
                if token and token in clean_keyword:
                    token_list.append(token)
            reduced_keyword = clean_keyword
            for generic_token in generic_token_list:
                reduced_keyword = reduced_keyword.replace(generic_token, " ")
            for token in re.split(r"[,，、;；\s]+", reduced_keyword):
                clean_token = token.strip()
                if len(clean_token) >= 2:
                    token_list.append(clean_token)
        return self.dedupe_text_list(token_list)

    def is_valid_rule_company_name(self, company_name: str) -> bool:
        if not is_valid_enterprise_name(company_name, []):
            return False
        if len(company_name) > 40:
            return False
        if self.is_ai_web_company_name_suspicious(company_name):
            return False
        invalid_token_list = (
            "名录",
            "黄页",
            "查询",
            "搜索",
            "企业名录",
            "厂家大全",
            "行业厂",
            "生产厂家",
            "生产厂",
            "批发商",
            "中国制造网",
            "供应商拥有",
            "批发网",
            "市场",
            "官方网站",
            "有限公司企业信息",
            "Copyright",
            "APP",
            "扫码",
            "关注",
            "进旺铺",
            "起订",
            "立即定制",
            "展开更多",
            "评价",
            "真实性保障",
            "服务保障",
            "买家",
            "商家",
            "真实工厂",
            "工厂档案",
            "综合概况",
            "联系使用",
        )
        if any(token in company_name for token in invalid_token_list):
            return False
        if KEYWORD_ONLY_COMPANY_PATTERN.fullmatch(company_name):
            return False
        if not self.is_high_confidence_rule_company_name(company_name):
            return False
        if re.search(r"\d{2,}", company_name):
            return False
        if company_name.endswith(("工厂", "厂")):
            if any(
                token in company_name
                for token in (
                    "工业区",
                    "工业园",
                    "产业园",
                    "产业转移",
                    "开发区",
                    "园区",
                    "源头工厂",
                    "路",
                    "号",
                    "院",
                    "栋",
                    "楼",
                    "县",
                    "镇",
                    "街",
                    "村",
                )
            ):
                return False
            category_token_list = [
                token
                for token_list in AI_WEB_CATEGORY_EVIDENCE_KEYWORD_MAP.values()
                for token in token_list
            ]
            if has_any_token(company_name, category_token_list):
                return False
            return bool(re.match(r"^(广东|广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|江门|湛江|肇庆|清远|揭阳|潮州)", company_name))
        return True

    def is_high_confidence_rule_company_name(self, company_name: str) -> bool:
        clean_name = clean_company_name_text(company_name)
        if clean_name.endswith(REAL_COMPANY_STRONG_SUFFIX_TUPLE):
            return True
        if not clean_name.endswith(FACTORY_COMPANY_SUFFIX_TUPLE):
            return False
        if has_any_token(clean_name, GENERIC_FACTORY_NAME_TOKEN_LIST):
            return False
        category_token_list = [
            token
            for token_list in AI_WEB_CATEGORY_EVIDENCE_KEYWORD_MAP.values()
            for token in token_list
        ]
        if has_any_token(clean_name, category_token_list):
            return False
        return has_any_token(clean_name, DETAILED_LOCATION_TOKEN_LIST)

    def build_phone_frequency_map(self, text: str) -> Dict[str, int]:
        frequency_map: Dict[str, int] = {}
        for phone in self.extract_public_phone_token_list(text):
            compact_phone = self.compact_phone_text(phone)
            if not compact_phone:
                continue
            frequency_map[compact_phone] = frequency_map.get(compact_phone, 0) + 1
        return frequency_map

    def extract_public_phone(self, text: str, phone_frequency_map: Optional[Dict[str, int]] = None) -> str:
        phone_list = []
        for phone in self.extract_public_phone_token_list(text):
            compact_phone = compact_phone_text(phone)
            if not compact_phone:
                continue
            if phone_frequency_map and phone_frequency_map.get(compact_phone, 0) > 2:
                continue
            phone_list.append(phone)
        return "；".join(dedupe_public_phone_list(phone_list[:5]))

    def extract_public_phone_token_list(self, text: str) -> List[str]:
        return extract_public_phone_token_list(text, include_service=True)

    def compact_phone_text(self, phone: str) -> str:
        return compact_phone_text(phone)

    def extract_address_text(self, text: str) -> str:
        match = re.search(r"(广东省|广东|广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|江门|湛江|肇庆|清远|揭阳|潮州)[^。；;\n]{4,120}", text or "")
        if not match:
            return ""
        return self.clean_text(match.group(0))[:200]

    def clean_product_text(self, value: str, fallback: str) -> str:
        text = self.clean_text(value)
        text = re.sub(r"[-_|].*$", "", text).strip()
        return (text or fallback)[:120]

    def pick_rule_product_name(self, title: str, context_text: str, industry: str, source_keyword: str) -> str:
        for value in (context_text, title):
            clean_value = self.clean_product_text(value, "")
            if clean_value and has_any_token(clean_value, INDUSTRY_RELEVANCE_KEYWORD_MAP.get(industry, [industry])):
                return clean_value[:120]
        for keyword in split_public_search_keyword(source_keyword):
            clean_keyword = self.clean_text(keyword)
            if clean_keyword:
                return clean_keyword[:120]
        return industry

    def is_ai_web_lead_relevant(self, lead: CollectedLeadDTO) -> bool:
        company_name = clean_company_name_text(lead.suspected_company_name)
        if self.is_ai_web_platform_company_name(company_name):
            return False
        if self.has_ai_web_non_target_company_bias(lead.industry, company_name):
            return False
        if is_industry_relevant_public_lead(lead):
            return True

        industry_token_list = INDUSTRY_RELEVANCE_KEYWORD_MAP.get(lead.industry, [lead.industry])
        strong_token_list = INDUSTRY_STRONG_RELEVANCE_KEYWORD_MAP.get(lead.industry, industry_token_list)
        evidence_text = self.clean_text(
            " ".join(
                [
                    company_name,
                    lead.product_name,
                    lead.business_scope,
                    lead.registered_address,
                    extract_public_labeled_business_text(lead.region_text),
                    lead.region_text,
                ]
            )
        )
        if not has_any_token(evidence_text, industry_token_list):
            return False
        if not self.has_ai_web_category_evidence(lead.industry, evidence_text):
            return False
        if not self.has_ai_web_supplier_intent(evidence_text, company_name):
            return False

        structured_text = self.clean_text(
            " ".join(
                [
                    company_name,
                    lead.product_name,
                    lead.business_scope,
                    extract_public_labeled_business_text(lead.region_text),
                ]
            )
        )
        if has_any_token(company_name, PUBLIC_COMPANY_WEAK_TARGET_TOKEN_LIST):
            return has_any_token(structured_text, strong_token_list)
        return has_any_token(company_name, industry_token_list) or has_any_token(evidence_text, BUSINESS_KEYWORD_LIST)

    def enrich_with_tianyancha(
        self,
        industry: str,
        lead_list: List[CollectedLeadDTO],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        company_name_list = []
        for lead in lead_list:
            company_name = clean_company_name_text(lead.suspected_company_name)
            if company_name and company_name not in company_name_list:
                company_name_list.append(company_name)
        if not company_name_list:
            return lead_list
        self.emit_task_event(
            "collecting",
            "info",
            f"AI 1688索引已找到 {len(company_name_list)} 个候选企业，开始用天眼查公开页补全联系人和电话。",
        )
        try:
            tianyancha_lead_list = self.tianyancha_collector.collect_by_company_names(
                industry=industry,
                company_name_list=company_name_list,
                collect_limit=min(len(company_name_list), collect_limit),
            )
        except Exception as ex:
            logger.exception("AI web search Tianyancha enrichment failed, error=%s", ex)
            self.emit_task_event(
                "collecting",
                "warning",
                f"天眼查补全失败，系统将先保留AI 1688索引结果；原因：{ex}",
            )
            return lead_list
        enrichment_map = self.build_enrichment_map(tianyancha_lead_list)
        enriched_count = 0
        for lead in lead_list:
            enrichment = self.find_enrichment_lead(lead.suspected_company_name, enrichment_map)
            if enrichment is None:
                continue
            self.merge_enrichment(lead, enrichment)
            enriched_count += 1
        self.emit_task_event("collecting", "info", f"天眼查补全完成：匹配 {enriched_count} 条。")
        return lead_list

    def build_enrichment_map(self, lead_list: List[CollectedLeadDTO]) -> Dict[str, CollectedLeadDTO]:
        result = {}
        for lead in lead_list:
            key = EnterprisePublicWebCollector.normalize_company_match_key(lead.suspected_company_name)
            if key and key not in result:
                result[key] = lead
        return result

    def find_enrichment_lead(
        self,
        company_name: str,
        enrichment_map: Dict[str, CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        key = EnterprisePublicWebCollector.normalize_company_match_key(company_name)
        if key in enrichment_map:
            return enrichment_map[key]
        return None

    def merge_enrichment(self, target: CollectedLeadDTO, source: CollectedLeadDTO) -> None:
        if has_public_phone_text(source.phone):
            target.phone = self.merge_text(target.phone, source.phone)
            target.phone_source = self.merge_text(target.phone_source, source.phone_source or "天眼查公开页可见字段")
        if is_valid_contact_name(source.contact_name):
            target.contact_name = source.contact_name
        elif not target.contact_name and is_valid_contact_name(source.legal_person):
            target.contact_name = source.legal_person
        for field_name in (
            "legal_person",
            "company_status",
            "unified_social_credit_code",
            "business_scope",
            "registered_address",
            "risk_tag",
        ):
            if not getattr(target, field_name) and getattr(source, field_name):
                setattr(target, field_name, getattr(source, field_name))
        target.region_text = self.merge_text(target.region_text, source.region_text)[:3000]
        target.is_enterprise_verified = target.is_enterprise_verified or source.is_enterprise_verified

    def collect_by_company_names(
        self,
        industry: str,
        company_name_list: List[str],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        return self.tianyancha_collector.collect_by_company_names(
            industry=industry,
            company_name_list=company_name_list,
            collect_limit=collect_limit,
        )

    def dedupe_lead_list(self, lead_list: List[CollectedLeadDTO], collect_limit: int) -> List[CollectedLeadDTO]:
        result_list = []
        dedupe_set = set()
        for lead in lead_list:
            key = clean_company_name_text(lead.suspected_company_name)
            if not key or key in dedupe_set:
                continue
            dedupe_set.add(key)
            result_list.append(lead)
            if len(result_list) >= collect_limit:
                break
        return result_list

    def is_existing_lead(self, lead: CollectedLeadDTO) -> bool:
        if not self.existing_dedupe_key_set:
            return False
        for value in (lead.suspected_company_name, lead.profile_url, lead.shop_url):
            key = self.normalize_dedupe_text(value)
            if key and key in self.existing_dedupe_key_set:
                return True
        return False

    def remember_lead(self, lead: CollectedLeadDTO) -> None:
        for value in (lead.suspected_company_name, lead.profile_url, lead.shop_url):
            key = self.normalize_dedupe_text(value)
            if key:
                self.existing_dedupe_key_set.add(key)

    def normalize_dedupe_text(self, value: str) -> str:
        return clean_company_name_text(value) or self.clean_text(value)

    def merge_text(self, left: str, right: str) -> str:
        return "；".join(self.dedupe_text_list([left, right]))

    def dedupe_text_list(self, text_list: List[str]) -> List[str]:
        result = []
        seen = set()
        for text in text_list:
            clean_text = self.clean_text(text)
            if not clean_text or clean_text in seen:
                continue
            seen.add(clean_text)
            result.append(clean_text)
        return result

    def clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()


class CollectorFactory:
    def get_collector(self, source_type: str):
        if source_type == SOURCE_TYPE_FENGNIAO_PUBLIC_WEB:
            return FengniaoPublicWebCollector()
        if source_type == SOURCE_TYPE_QCC_PUBLIC_WEB:
            return QichachaPublicWebCollector()
        if source_type == SOURCE_TYPE_AIQICHA_PUBLIC_WEB:
            return EnterprisePublicWebCollector.create_aiqicha_collector()
        if source_type == SOURCE_TYPE_QIXIN_PUBLIC_WEB:
            return EnterprisePublicWebCollector.create_qixin_collector()
        if source_type == SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB:
            return EnterprisePublicWebCollector.create_tianyancha_collector()
        if source_type == SOURCE_TYPE_AI_WEB_SEARCH:
            return AiWebSearchCollector()
        if source_type == SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT:
            return Alibaba1688PageAssistantCollector()
        if source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            return MadeInChinaTianyanchaCollector()
        if source_type == SOURCE_TYPE_ALIBABA_1688:
            return Alibaba1688PublicPageCollector()
        if source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            from app.service.alibaba_international_collector import AlibabaInternationalSupplierCollector

            return AlibabaInternationalSupplierCollector()
        return DouyinPublicCollector()
