from app.core.constant import LEAD_LEVEL_A, LEAD_LEVEL_B, LEAD_LEVEL_C, LEAD_LEVEL_D
from app.model.schema import CollectedLeadDTO, CompanyVerifyDTO, ScoreResultDTO


class ScoringService:
    def calculate_score(
        self,
        collected_lead: CollectedLeadDTO,
        company_verify: CompanyVerifyDTO,
    ) -> ScoreResultDTO:
        score = 0
        business_text = self.build_business_text(collected_lead, company_verify)
        keyword_list = self.split_keyword_text(collected_lead.source_keyword)
        if collected_lead.industry and collected_lead.industry in business_text:
            score += 25
        elif any(keyword in business_text for keyword in keyword_list):
            score += 15
        if company_verify.company_status in ("存续", "在业") and company_verify.is_success:
            score += 15
        if collected_lead.is_blue_v or collected_lead.is_enterprise_verified:
            score += 10
        if self.has_public_phone(collected_lead.phone) or self.has_public_phone(company_verify.phone):
            score += 12
        if collected_lead.website_url or collected_lead.shop_url:
            score += 8
        if collected_lead.recent_video_count_30d >= 4 or collected_lead.source_type in (
            "alibaba_1688",
            "alibaba_1688_page_assistant",
            "alibaba_1688_page_import",
            "qcc_public_web",
            "fengniao_public_web",
            "aiqicha_public_web",
            "qixin_public_web",
            "tianyancha_public_web",
            "ai_web_search",
        ):
            score += 15
        if collected_lead.commercial_keyword_count >= 2:
            score += 10
        if "异常" in company_verify.risk_tag:
            score -= 20
        score = max(min(score, 100), 0)
        return ScoreResultDTO(score=score, level=self.get_level(score))

    def has_public_phone(self, phone_text: str) -> bool:
        return bool(phone_text and any(char.isdigit() for char in phone_text))

    def build_business_text(self, collected_lead: CollectedLeadDTO, company_verify: CompanyVerifyDTO) -> str:
        return " ".join(
            [
                collected_lead.product_name or "",
                collected_lead.business_scope or "",
                company_verify.business_scope or "",
                company_verify.company_name or "",
                collected_lead.suspected_company_name or "",
            ]
        )

    def split_keyword_text(self, keyword_text: str) -> list:
        return [
            keyword.strip()
            for keyword in (keyword_text or "").replace("，", ",").replace("、", ",").split(",")
            if len(keyword.strip()) >= 2
        ]

    def get_level(self, score: int) -> str:
        if score >= 80:
            return LEAD_LEVEL_A
        if score >= 60:
            return LEAD_LEVEL_B
        if score >= 40:
            return LEAD_LEVEL_C
        return LEAD_LEVEL_D
