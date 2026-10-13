from app.core.config import get_config
from app.core.constant import VERIFY_STATUS_SKIPPED
from app.model.schema import CompanyVerifyDTO


class QichachaService:
    def __init__(self):
        self.config = get_config()

    def verify_company(self, company_name: str, industry: str) -> CompanyVerifyDTO:
        if not self.config.qcc_api_key or not self.config.qcc_api_secret:
            return self.build_unverified_result(company_name, "企查查 API 未配置")
        return self.build_unverified_result(company_name, "企查查真实 API 适配器待接入")

    def build_unverified_result(self, company_name: str, failure_reason: str) -> CompanyVerifyDTO:
        return CompanyVerifyDTO(
            company_name=company_name,
            legal_person="",
            company_status="未核验",
            business_scope="",
            registered_address="",
            phone="",
            risk_tag="",
            verification_status=VERIFY_STATUS_SKIPPED,
            confidence="low",
            is_success=False,
            failure_reason=failure_reason,
            consume_count=0,
        )
