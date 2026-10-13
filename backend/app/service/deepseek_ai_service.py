import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_config
from app.core.constant import SOURCE_TYPE_AI_WEB_SEARCH, SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT
from app.model.schema import CollectedLeadDTO
from app.util.contact_name_util import normalize_contact_name
from app.util.phone_filter_util import clean_public_phone_text

logger = logging.getLogger(__name__)

CAPTCHA_TOKEN_LIST = (
    "请完成验证",
    "安全验证",
    "验证码",
    "拖动下方滑块",
    "通过验证以确保正常访问",
    "身份验证以继续使用",
    "点击按钮开始验证",
)
LOGIN_TOKEN_LIST = ("登录", "注册", "passport", "login")
INVALID_COMPANY_TOKEN_LIST = ("登录", "注册", "验证码", "搜索", "首页", "阿里巴巴", "1688")
INDUSTRY_KEYWORD_TOKEN_MAP = {
    "服装": ("服装", "女装", "男装", "童装", "服饰", "衣服", "制衣", "针织", "梭织", "牛仔", "内衣", "鞋帽"),
    "3C数码": ("3C", "数码", "电子", "手机", "数据线", "耳机", "充电", "配件", "电源", "蓝牙", "屏幕"),
    "美妆个护": ("化妆", "护肤", "美妆", "彩妆", "口红", "面膜", "香水", "洗护", "OEM", "代工"),
}


@dataclass
class AiPageAnalysisResult:
    page_state: str = "unknown"
    reason: str = ""
    lead_list: List[CollectedLeadDTO] = field(default_factory=list)


class DeepSeekAiService:
    def __init__(self):
        self.config = get_config()

    def is_enabled(self) -> bool:
        return bool(self.config.ai_page_recognition_enabled and self.config.deepseek_api_key)

    def analyze_1688_snapshot(
        self,
        industry: str,
        source_keyword: str,
        page_url: str,
        page_title: str,
        page_text: str,
        card_list: List[Dict],
        collect_limit: int,
        source_type: str = SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
    ) -> AiPageAnalysisResult:
        if not self.is_enabled():
            return AiPageAnalysisResult(reason="DeepSeek AI recognition is disabled or API key is empty.")

        local_state = self.detect_local_page_state(page_url, page_title, page_text)
        payload = self.build_1688_snapshot_payload(
            industry=industry,
            source_keyword=source_keyword,
            page_url=page_url,
            page_title=page_title,
            page_text=page_text,
            card_list=card_list,
            collect_limit=collect_limit,
        )
        response_data = self.request_json(
            system_prompt=self.build_1688_system_prompt(),
            user_payload=payload,
        )
        page_state = str(response_data.get("page_state") or local_state or "unknown").strip()
        reason = str(response_data.get("reason") or "").strip()
        lead_list = self.build_lead_list(
            raw_lead_list=response_data.get("leads") if isinstance(response_data.get("leads"), list) else [],
            industry=industry,
            source_keyword=source_keyword,
            page_url=page_url,
            source_type=source_type,
            collect_limit=collect_limit,
        )
        return AiPageAnalysisResult(page_state=page_state, reason=reason, lead_list=lead_list)

    def build_lead_discovery_keywords(
        self,
        industry: str,
        source_type: str,
        raw_keyword_list: List[str],
        collect_limit: int,
    ) -> Dict:
        if not self.is_enabled():
            return {"keywords": [], "reason": "DeepSeek AI recognition is disabled or API key is empty."}
        payload = {
            "task": "为公开页面企业线索采集生成更精准的中文搜索关键词。",
            "industry": industry,
            "source_type": source_type,
            "raw_keywords": raw_keyword_list,
            "collect_limit": collect_limit,
            "constraints": [
                "目标是广东地区工厂、批发商、OEM、供应链企业",
                f"所有关键词必须紧扣行业：{industry}，不得生成其它行业关键词",
                "关键词要适合1688、天眼查、企查查等公开页面搜索",
                "不要生成绕过登录、验证码、安全验证或风控的方法",
                "不要编造企业名、联系人或电话号码",
                "返回5到10个高命中关键词，优先包含品类、工厂/批发/OEM、广东城市或跨境属性",
            ],
        }
        data = self.request_json(
            system_prompt=self.build_keyword_strategy_system_prompt(),
            user_payload=payload,
        )
        keyword_list = self.normalize_keyword_list(data.get("keywords"))
        keyword_list = self.filter_keyword_list_by_industry(keyword_list, industry, raw_keyword_list)
        reason = self.clean_text(str(data.get("reason") or ""))
        return {"keywords": keyword_list[:10], "reason": reason}

    def analyze_public_web_documents(
        self,
        industry: str,
        source_keyword: str,
        document_list: List[Dict],
        collect_limit: int,
        source_type: str = SOURCE_TYPE_AI_WEB_SEARCH,
    ) -> AiPageAnalysisResult:
        if not self.is_enabled():
            return AiPageAnalysisResult(reason="DeepSeek AI recognition is disabled or API key is empty.")
        payload = self.build_public_web_document_payload(
            industry=industry,
            source_keyword=source_keyword,
            document_list=document_list,
            collect_limit=collect_limit,
        )
        response_data = self.request_json(
            system_prompt=self.build_public_web_document_system_prompt(),
            user_payload=payload,
        )
        page_state = str(response_data.get("page_state") or "normal").strip()
        reason = str(response_data.get("reason") or "").strip()
        lead_list = self.build_lead_list(
            raw_lead_list=response_data.get("leads") if isinstance(response_data.get("leads"), list) else [],
            industry=industry,
            source_keyword=source_keyword,
            page_url="",
            source_type=source_type,
            collect_limit=collect_limit,
        )
        return AiPageAnalysisResult(page_state=page_state, reason=reason, lead_list=lead_list)

    def build_public_web_document_payload(
        self,
        industry: str,
        source_keyword: str,
        document_list: List[Dict],
        collect_limit: int,
    ) -> Dict:
        max_chars = max(4000, self.config.deepseek_max_input_chars)
        compact_document_list = []
        remaining_chars = max_chars
        for document in document_list[:30]:
            text = self.clean_text(str(document.get("text") or ""))
            snippet = self.clean_text(str(document.get("snippet") or ""))
            title = self.clean_text(str(document.get("title") or ""))
            url = str(document.get("url") or "")
            if not title and not snippet and not text:
                continue
            text_budget = max(600, min(2500, remaining_chars))
            compact_document_list.append(
                {
                    "title": title[:200],
                    "url": url[:1024],
                    "snippet": snippet[:500],
                    "text": text[:text_budget],
                }
            )
            remaining_chars -= text_budget
            if remaining_chars <= 0:
                break
        return {
            "task": "从搜索引擎已收录的1688公开摘要中识别广东企业线索。",
            "industry": industry,
            "source_keyword": source_keyword,
            "collect_limit": collect_limit,
            "documents": compact_document_list,
        }

    def build_public_web_document_system_prompt(self) -> str:
        return (
            "你是1688企业线索识别助手。必须只根据输入的搜索引擎1688索引标题、摘要和公开文本抽取企业线索。"
            "目标只要广东企业，优先工厂、批发、OEM、供应链。"
            "候选必须同时满足：1）与当前行业品类直接相关；2）页面证据显示它是工厂、厂家、批发商、供应商、OEM、ODM、代工、生产、制造、加工、供应链或跨境外贸企业。"
            "source_keyword 和搜索词只能理解任务目标，不能作为企业名、产品、电话或行业相关证据；所有证据必须来自 documents 的 title/snippet/text。"
            "company_name 必须是输入文本中逐字出现的真实企业主体名称，优先选择包含“有限公司、商行、经营部、工作室、集团、分公司”等主体后缀的名称；"
            "只有在文本中出现明确店铺主体时，才允许使用“厂/工厂”结尾的名称。"
            "不得把“广州化妆品OEM加工厂、深圳数据线工厂、服装工厂、手机壳工厂、供应商、生产厂家、企业名录、行业厂、某某平台/网站”当企业名。"
            "不要把腾讯、阿里巴巴、百度、字节跳动、网易、京东、美团等互联网平台或泛软件公司当作供应商线索，除非输入文本明确显示其为当前品类工厂/批发/OEM供应商。"
            "候选企业可以先没有电话和联系人；如果电话或联系人在输入文本中没有明确出现，对应字段必须返回空字符串。"
            "不要编造企业、联系人、电话；电话必须在输入文本中明确出现才可填写。"
            "联系人必须来自明确的联系人、负责人、法定代表人、经营者等公开字段；不要从普通句子里猜人名。"
            "遇到登录、验证码、会员墙、付费墙、访问受限内容，只能标记原因，不要提供绕过方法。"
            "只输出 JSON，不要输出 Markdown。JSON 格式："
            "{\"page_state\":\"normal|verification_required|empty|unknown\","
            "\"reason\":\"简短原因\","
            "\"leads\":[{\"company_name\":\"企业名\",\"product_name\":\"主营/产品\","
            "\"contact_name\":\"联系人或法人\",\"phone\":\"公开电话\",\"phone_source\":\"电话来源\","
            "\"registered_address\":\"地址\",\"business_scope\":\"经营范围\","
            "\"risk_tag\":\"风险标签\",\"shop_url\":\"官网或店铺链接\",\"profile_url\":\"来源链接\","
            "\"is_guangdong\":true}]}"
        )

    def build_keyword_strategy_system_prompt(self) -> str:
        return (
            "你是公开企业线索采集策略助手。你只生成搜索关键词，不输出任何真实企业数据。"
            "必须遵守网站登录、验证码和访问限制，不要提供绕过验证、伪装身份、规避风控的方法。"
            "只输出 JSON，不要输出 Markdown。JSON 格式："
            "{\"keywords\":[\"关键词1\",\"关键词2\"],\"reason\":\"生成思路\"}"
        )

    def build_1688_snapshot_payload(
        self,
        industry: str,
        source_keyword: str,
        page_url: str,
        page_title: str,
        page_text: str,
        card_list: List[Dict],
        collect_limit: int,
    ) -> Dict:
        max_chars = max(4000, self.config.deepseek_max_input_chars)
        compact_card_list = []
        for card in card_list[:80]:
            text = self.clean_text(str(card.get("text") or ""))
            href = str(card.get("href") or "")
            if not text:
                continue
            compact_card_list.append(
                {
                    "text": text[:1200],
                    "href": href[:500],
                }
            )
        clean_page_text = self.clean_text(page_text)[:max_chars]
        return {
            "task": "识别1688公开页面中的企业线索，只使用输入文本中已经公开可见的信息。",
            "industry": industry,
            "source_keyword": source_keyword,
            "collect_limit": collect_limit,
            "page": {
                "url": page_url,
                "title": page_title,
                "text": clean_page_text,
            },
            "cards": compact_card_list,
        }

    def build_1688_system_prompt(self) -> str:
        return (
            "你是企业线索页面识别助手。必须只根据用户提供的1688页面文本和卡片文本抽取公开可见字段，"
            "不能编造、不能推测不可见电话。若页面是登录、验证码、滑块、安全验证或访问受限，"
            "page_state 返回 verification_required 或 login_required，并且不要尝试绕过验证。"
            "只输出 JSON，不要输出 Markdown。JSON 格式："
            "{\"page_state\":\"normal|login_required|verification_required|empty|unknown\","
            "\"reason\":\"简短原因\","
            "\"leads\":[{\"company_name\":\"企业名\",\"product_name\":\"主营/产品\","
            "\"contact_name\":\"联系人或法人\",\"phone\":\"公开电话\",\"phone_source\":\"电话来源\","
            "\"registered_address\":\"地址\",\"business_scope\":\"经营范围\","
            "\"risk_tag\":\"风险标签\",\"shop_url\":\"店铺链接\",\"profile_url\":\"详情链接\","
            "\"is_guangdong\":true}]}"
        )

    def request_json(self, system_prompt: str, user_payload: Dict) -> Dict:
        url = f"{self.config.deepseek_base_url}/chat/completions"
        request_body = {
            "model": self.config.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = Request(
            url,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.deepseek_timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as ex:
            error_body = ex.read().decode("utf-8", errors="ignore")[:500]
            raise RuntimeError(f"DeepSeek API request failed: HTTP {ex.code} {error_body}") from ex
        except URLError as ex:
            raise RuntimeError(f"DeepSeek API request failed: {ex.reason}") from ex

        content = (
            response_payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return self.parse_json_content(content)

    def parse_json_content(self, content: str) -> Dict:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        start_index = text.find("{")
        end_index = text.rfind("}")
        if start_index >= 0 and end_index > start_index:
            text = text[start_index : end_index + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as ex:
            raise RuntimeError("DeepSeek API did not return valid JSON.") from ex
        if not isinstance(data, dict):
            raise RuntimeError("DeepSeek API JSON response must be an object.")
        return data

    def normalize_keyword_list(self, raw_keyword_list) -> List[str]:
        if not isinstance(raw_keyword_list, list):
            return []
        result_list = []
        seen = set()
        for item in raw_keyword_list:
            keyword = self.clean_text(str(item or ""))
            keyword = re.sub(r"[，,、；;]+", " ", keyword).strip()
            if len(keyword) < 2 or len(keyword) > 40:
                continue
            if any(token in keyword for token in ("验证码", "绕过", "破解", "cookie", "代理池")):
                continue
            if keyword in seen:
                continue
            seen.add(keyword)
            result_list.append(keyword)
        return result_list

    def filter_keyword_list_by_industry(
        self,
        keyword_list: List[str],
        industry: str,
        fallback_keyword_list: List[str],
    ) -> List[str]:
        token_list = INDUSTRY_KEYWORD_TOKEN_MAP.get(industry, ())
        if not token_list:
            return keyword_list
        filtered_keyword_list = [
            keyword
            for keyword in keyword_list
            if any(token.lower() in keyword.lower() for token in token_list)
        ]
        if len(filtered_keyword_list) >= 3:
            return filtered_keyword_list
        fallback_list = self.normalize_keyword_list(fallback_keyword_list)
        for keyword in fallback_list:
            if keyword not in filtered_keyword_list:
                filtered_keyword_list.append(keyword)
        return filtered_keyword_list

    def build_lead_list(
        self,
        raw_lead_list: List[Dict],
        industry: str,
        source_keyword: str,
        page_url: str,
        source_type: str,
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        result_list: List[CollectedLeadDTO] = []
        dedupe_set = set()
        for item in raw_lead_list:
            if len(result_list) >= collect_limit:
                break
            if not isinstance(item, dict):
                continue
            company_name = self.clean_company_name(str(item.get("company_name") or ""))
            if not self.is_valid_company_name(company_name):
                continue
            dedupe_key = company_name.replace(" ", "")
            if dedupe_key in dedupe_set:
                continue
            dedupe_set.add(dedupe_key)
            phone = self.normalize_phone(str(item.get("phone") or ""))
            registered_address = self.clean_text(str(item.get("registered_address") or ""))
            is_guangdong = bool(item.get("is_guangdong"))
            region_text = registered_address
            if is_guangdong and "广东" not in region_text:
                region_text = f"广东 {region_text}".strip()
            result_list.append(
                CollectedLeadDTO(
                    source_type=source_type,
                    source_keyword=source_keyword,
                    industry=industry,
                    suspected_company_name=company_name,
                    product_name=self.clean_text(str(item.get("product_name") or ""))[:120],
                    contact_name=self.clean_contact_name(str(item.get("contact_name") or "")),
                    phone=phone,
                    phone_source=self.clean_text(str(item.get("phone_source") or "DeepSeek AI识别公开字段"))[:120]
                    if phone
                    else "",
                    business_scope=self.clean_text(str(item.get("business_scope") or ""))[:500],
                    registered_address=registered_address[:300],
                    risk_tag=self.clean_text(str(item.get("risk_tag") or ""))[:200],
                    region_text=region_text[:3000],
                    shop_url=self.pick_url(str(item.get("shop_url") or ""), page_url),
                    profile_url=self.pick_url(str(item.get("profile_url") or ""), page_url),
                    is_enterprise_verified=True,
                    commercial_keyword_count=1,
                )
            )
        return result_list

    def detect_local_page_state(self, page_url: str, page_title: str, page_text: str) -> str:
        text = " ".join([page_url or "", page_title or "", page_text or ""])[:6000]
        lower_text = text.lower()
        if any(token in text for token in CAPTCHA_TOKEN_LIST):
            return "verification_required"
        if any(token in lower_text for token in LOGIN_TOKEN_LIST):
            return "login_required"
        return "unknown"

    def clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def clean_company_name(self, value: str) -> str:
        value = self.clean_text(value)
        value = re.sub(r"^[^\u4e00-\u9fa5A-Za-z0-9]+|[^\u4e00-\u9fa5A-Za-z0-9)）]+$", "", value)
        return value[:100]

    def is_valid_company_name(self, value: str) -> bool:
        if len(value) < 3:
            return False
        if any(token in value for token in INVALID_COMPANY_TOKEN_LIST):
            return False
        if re.fullmatch(
            r"(?:广东|广州|深圳|东莞|佛山|中山|珠海|惠州|汕头|潮州|揭阳|江门|肇庆|"
            r"湛江|茂名|阳江|清远|韶关|梅州|河源|汕尾|云浮)?(?:省|市|区|县)?"
            r"(?:服装|女装|男装|童装|内衣|鞋|鞋业|手机壳|数据线|耳机|充电器|数码|"
            r"3C|化妆品|护肤品|美妆|彩妆|面膜|日化)"
            r"(?:(?:工厂|厂|厂家|批发|供应链|OEM|ODM|代工|加工|加工厂|生产厂家|源头厂家))*"
            r"(?:有限公司)?",
            value,
            flags=re.IGNORECASE,
        ):
            return False
        if any(token in value for token in ("有限公司", "有限责任公司", "股份有限公司", "集团", "分公司", "商行", "经营部", "工作室")):
            return True
        if value.endswith(("工厂", "厂")):
            if any(token in value for token in ("OEM", "ODM", "代工", "加工", "批发", "厂家", "供应商", "供应链", "源头")):
                return False
            return any(token in value for token in ("区", "县", "镇", "街道", "街", "村", "工业区", "工业园", "产业园", "科技园", "开发区"))
        return False

    def clean_contact_name(self, value: str) -> str:
        return normalize_contact_name(value)

    def normalize_phone(self, value: str) -> str:
        return clean_public_phone_text(value, include_service=False)

    def pick_url(self, value: str, fallback_url: str) -> str:
        clean_value = self.clean_text(value)
        if clean_value.startswith("http://") or clean_value.startswith("https://"):
            return clean_value[:1024]
        return (fallback_url or "")[:1024]
