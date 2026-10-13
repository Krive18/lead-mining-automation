import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from app.core.config import get_config
from app.core.constant import SOURCE_TYPE_QIXIN_PUBLIC_WEB
from app.model.schema import CollectedLeadDTO
from app.util.address_util import clean_registered_address_text
from app.util.contact_name_util import normalize_contact_name
from app.util.credit_code_util import clean_unified_social_credit_code
from app.util.phone_filter_util import clean_public_phone_text


QIXIN_BASIC_ENDPOINT = "/enterprise/getBasicInfo"
QIXIN_CONTACT_ENDPOINT = "/enterprise/getContactInfo"
QIXIN_PARTNERS_ENDPOINT = "/enterprise/getPartners"
QIXIN_ENDPOINT_MAP = {
    "basic": QIXIN_BASIC_ENDPOINT,
    "contact": QIXIN_CONTACT_ENDPOINT,
    "partners": QIXIN_PARTNERS_ENDPOINT,
}


class QixinApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        endpoint: str = "",
        status: str = "",
        error_code: str = "",
    ):
        super().__init__(message)
        self.endpoint = endpoint
        self.status = str(status or "")
        self.error_code = str(error_code or "")

    def is_authorization_denied(self) -> bool:
        message = str(self)
        return self.status in {"401", "403"} or any(
            token in message
            for token in (
                "未授权",
                "无权限",
                "没有权限",
                "权限不足",
                "套餐",
                "未开通",
                "鉴权失败",
                "签名错误",
                "IP白名单",
                "ip白名单",
            )
        )


@dataclass
class QixinCompanyResult:
    lead: CollectedLeadDTO
    endpoint_status: Dict[str, Dict] = field(default_factory=dict)


class QixinApiService:
    def __init__(self, config=None, transport: Optional[Callable] = None):
        self.config = config or get_config()
        self.http_opener = build_opener(ProxyHandler({}))
        self.transport = transport or self.http_get_json

    def is_configured(self) -> bool:
        return bool(self.config.qixin_app_key and self.config.qixin_secret_key)

    def assert_configured(self) -> None:
        if not self.is_configured():
            raise QixinApiError("启信宝 API 未配置，请先设置 QIXIN_APP_KEY 和 QIXIN_SECRET_KEY。")

    def get_connection_status(self) -> Dict[str, object]:
        status = {
            "configured": self.is_configured(),
            "egress_ip": "",
            "egress_region": "",
            "message": "",
        }
        try:
            request = Request(
                "https://myip.ipip.net",
                headers={"User-Agent": "Mozilla/5.0 LeadMining/QixinStatus"},
                method="GET",
            )
            with self.http_opener.open(request, timeout=min(float(self.config.qixin_timeout_seconds), 15.0)) as response:
                response_text = response.read().decode("utf-8", errors="replace").strip()
            ip_match = re.search(r"(?:IP[：:]\s*)?(\d{1,3}(?:\.\d{1,3}){3})", response_text, flags=re.IGNORECASE)
            region_match = re.search(r"来自于[：:]\s*(.+)$", response_text)
            status["egress_ip"] = ip_match.group(1) if ip_match else ""
            status["egress_region"] = region_match.group(1).strip() if region_match else ""
            status["message"] = "启信宝API已配置，白名单需包含当前出口IP" if status["configured"] else "启信宝API密钥未配置"
        except Exception as ex:
            status["message"] = f"启信宝API已配置，但出口IP检测失败：{str(ex)[:120]}" if status["configured"] else "启信宝API密钥未配置"
        return status

    def build_auth_headers(self, timestamp: Optional[int] = None) -> Dict[str, str]:
        self.assert_configured()
        timestamp_value = int(timestamp if timestamp is not None else time.time() * 1000)
        sign_source = f"{self.config.qixin_app_key}{timestamp_value}{self.config.qixin_secret_key}"
        sign = hashlib.md5(sign_source.encode("utf-8")).hexdigest()
        return {
            "Auth-Version": "2.0",
            "appkey": self.config.qixin_app_key,
            "timestamp": str(timestamp_value),
            "sign": sign,
            "Accept": "application/json",
        }

    def http_get_json(self, endpoint: str, params: Dict, headers: Dict, timeout: float) -> Dict:
        url = f"{self.config.qixin_base_url}{endpoint}?{urlencode(params)}"
        request = Request(url, headers=headers, method="GET")
        try:
            with self.http_opener.open(request, timeout=timeout) as response:
                raw_body = response.read()
        except HTTPError as ex:
            raw_body = ex.read()
            message = self.decode_error_message(raw_body) or f"启信宝 API HTTP {ex.code}"
            raise QixinApiError(message, endpoint=endpoint, status=str(ex.code)) from ex
        except (URLError, TimeoutError) as ex:
            raise QixinApiError(f"启信宝 API 网络请求失败：{ex}", endpoint=endpoint) from ex
        try:
            return json.loads(raw_body.decode("utf-8", errors="replace"))
        except (TypeError, ValueError) as ex:
            raise QixinApiError("启信宝 API 返回了无法解析的 JSON。", endpoint=endpoint) from ex

    @staticmethod
    def decode_error_message(raw_body: bytes) -> str:
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="replace"))
        except (TypeError, ValueError):
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("message") or payload.get("msg") or payload.get("error") or "").strip()

    def request_endpoint(self, endpoint: str, company_name: str) -> Dict:
        clean_company_name = str(company_name or "").strip()
        if not clean_company_name:
            raise QixinApiError("启信宝查询企业名称不能为空。", endpoint=endpoint)
        payload = self.transport(
            endpoint,
            {"keyword": clean_company_name},
            self.build_auth_headers(),
            float(self.config.qixin_timeout_seconds),
        )
        if not isinstance(payload, dict):
            raise QixinApiError("启信宝 API 返回格式异常。", endpoint=endpoint)
        status = str(payload.get("status") or payload.get("code") or "").strip()
        data = payload.get("data")
        if status.lower() not in {"200", "success", "0"} and not (not status and data):
            message = str(payload.get("message") or payload.get("msg") or "启信宝 API 查询失败").strip()
            raise QixinApiError(
                message,
                endpoint=endpoint,
                status=status,
                error_code=str(payload.get("error_code") or payload.get("errorCode") or ""),
            )
        if data is None:
            raise QixinApiError("启信宝 API 未返回企业数据。", endpoint=endpoint, status=status)
        return payload

    def query_company(self, company_name: str, industry: str) -> QixinCompanyResult:
        self.assert_configured()
        endpoint_status = {}
        basic_payload = self.request_endpoint(QIXIN_BASIC_ENDPOINT, company_name)
        endpoint_status["basic"] = self.build_success_status(basic_payload)
        basic_data = self.first_mapping(basic_payload.get("data"))
        if not basic_data:
            raise QixinApiError("启信宝工商照面未返回有效企业数据。", endpoint=QIXIN_BASIC_ENDPOINT)

        contact_data = {}
        partner_data = None
        for status_key, endpoint in (("contact", QIXIN_CONTACT_ENDPOINT), ("partners", QIXIN_PARTNERS_ENDPOINT)):
            try:
                payload = self.request_endpoint(endpoint, company_name)
                endpoint_status[status_key] = self.build_success_status(payload)
                if status_key == "contact":
                    contact_data = self.first_mapping(payload.get("data"))
                else:
                    partner_data = payload.get("data")
            except QixinApiError as ex:
                endpoint_status[status_key] = self.build_error_status(ex)

        lead = self.build_lead(company_name, industry, basic_data, contact_data, partner_data)
        return QixinCompanyResult(lead=lead, endpoint_status=endpoint_status)

    def build_lead(
        self,
        requested_company_name: str,
        industry: str,
        basic_data: Dict,
        contact_data: Dict,
        partner_data,
    ) -> CollectedLeadDTO:
        company_name = self.pick_text(
            basic_data,
            "name",
            "entName",
            "enterprise_name",
            "enterpriseName",
        ) or requested_company_name
        legal_person = normalize_contact_name(
            self.pick_text(basic_data, "oper_name", "operName", "legalPerson", "legalPersonName", "legal_person")
        )
        registered_address = clean_registered_address_text(
            self.pick_text(contact_data, "address", "registeredAddress", "registered_address")
            or self.pick_text(basic_data, "address", "registeredAddress", "registered_address", "regAddress")
        )
        phone = self.clean_qixin_contact_phone(
            self.pick_text(contact_data, "telephone", "phone", "mobile", "tel", "telephoneNumber")
        )
        max_shareholder_name = self.pick_largest_person_shareholder(partner_data)
        contact_name = self.format_role_contact_name(legal_person, max_shareholder_name)
        return CollectedLeadDTO(
            source_type=SOURCE_TYPE_QIXIN_PUBLIC_WEB,
            source_keyword=requested_company_name,
            industry=industry,
            suspected_company_name=company_name,
            product_name="",
            contact_name=contact_name or legal_person,
            phone=phone,
            phone_source="启信宝1.51企业联系方式" if phone else "启信宝未返回公开电话",
            legal_person=legal_person,
            company_status=self.pick_text(basic_data, "status", "businessStatus", "status_name", "regStatus"),
            unified_social_credit_code=clean_unified_social_credit_code(
                self.pick_text(basic_data, "credit_no", "creditNo", "creditCode", "unifiedSocialCreditCode")
            ),
            business_scope=self.pick_text(basic_data, "scope", "businessScope", "business_scope"),
            registered_address=registered_address,
            region_text=f"启信宝API {registered_address}".strip(),
            profile_url="https://www.qixin.com/search?" + urlencode({"key": company_name}),
            is_enterprise_verified=True,
        )

    @staticmethod
    def first_mapping(data) -> Dict:
        if isinstance(data, dict):
            for key in ("result", "item", "items", "list", "records"):
                value = data.get(key)
                if isinstance(value, dict):
                    return value
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value[0]
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return {}

    @staticmethod
    def clean_qixin_contact_phone(phone_text: str) -> str:
        return clean_public_phone_text(
            phone_text,
            include_service=True,
            include_landline=False,
        )

    @staticmethod
    def pick_text(data: Dict, *key_list: str) -> str:
        for key in key_list:
            value = data.get(key) if isinstance(data, dict) else None
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                value = "、".join(str(item).strip() for item in value if str(item).strip())
            clean_value = str(value).strip()
            if clean_value and clean_value.lower() not in {"none", "null", "-"}:
                return clean_value
        return ""

    def pick_largest_person_shareholder(self, data) -> str:
        item_list = self.extract_mapping_list(data)
        candidate_list = []
        for index, item in enumerate(item_list):
            name = self.pick_text(item, "name", "partnerName", "stock_name", "shareholderName", "holderName")
            shareholder_type = self.pick_text(item, "type", "partnerType", "stock_type", "shareholderType")
            if not self.is_person_shareholder(name, shareholder_type):
                continue
            ratio_text = self.pick_text(item, "percent", "ratio", "stockPercent", "shareRatio", "fundedRatio")
            ratio = self.parse_ratio(ratio_text)
            candidate_list.append((ratio, -index, name))
        if not candidate_list:
            return ""
        return max(candidate_list)[2]

    def extract_mapping_list(self, data) -> List[Dict]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("items", "partners", "partnerList", "list", "records", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested_list = self.extract_mapping_list(value)
                if nested_list:
                    return nested_list
        return []

    @staticmethod
    def is_person_shareholder(name: str, shareholder_type: str) -> bool:
        if not name:
            return False
        if "自然人" in shareholder_type:
            return True
        if any(token in name for token in ("公司", "企业", "合伙", "集团", "投资", "基金", "中心")):
            return False
        return bool(re.fullmatch(r"[\u3400-\u9fff·]{2,6}", name))

    @staticmethod
    def parse_ratio(value: str) -> float:
        match = re.search(r"\d+(?:\.\d+)?", value or "")
        return float(match.group(0)) if match else -1.0

    @staticmethod
    def format_role_contact_name(legal_person: str, max_shareholder_name: str) -> str:
        if legal_person and max_shareholder_name:
            if legal_person == max_shareholder_name:
                return f"法人/最大股东：{legal_person}"
            return f"法人：{legal_person}；最大股东：{max_shareholder_name}"
        if legal_person:
            return f"法人：{legal_person}"
        if max_shareholder_name:
            return f"最大股东：{max_shareholder_name}"
        return ""

    @staticmethod
    def build_success_status(payload: Dict) -> Dict:
        return {
            "authorized": True,
            "success": True,
            "status": str(payload.get("status") or payload.get("code") or "200"),
            "message": str(payload.get("message") or payload.get("msg") or "success"),
        }

    @staticmethod
    def build_error_status(error: QixinApiError) -> Dict:
        return {
            "authorized": False if error.is_authorization_denied() else None,
            "success": False,
            "status": error.status,
            "message": str(error),
            "error_code": error.error_code,
        }
