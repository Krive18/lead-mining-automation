import re
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.constant import SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_ALIBABA_INTERNATIONAL, SOURCE_TYPE_DOUYIN_QCC


CHINESE_TEXT_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class TaskCreateDTO(BaseModel):
    source_type: Literal[
        "douyin_qcc",
        "qcc_public_web",
        "fengniao_public_web",
        "aiqicha_public_web",
        "qixin_public_web",
        "tianyancha_public_web",
        "ai_web_search",
        "alibaba_1688",
        "alibaba_1688_page_assistant",
        "alibaba_1688_page_import",
        "alibaba_international",
        "made_in_china_tianyancha",
    ] = SOURCE_TYPE_DOUYIN_QCC
    industry: str = Field(default="服装", min_length=1, max_length=20)
    keywords: List[str] = Field(default_factory=list)
    target_city: str = Field(default="广东省", max_length=255)
    collect_limit: int = Field(default=30, ge=1, le=1200)
    is_qcc_enabled: bool = True
    qcc_limit: int = Field(default=20, ge=0, le=1200)

    @model_validator(mode="after")
    def validate_keyword_rules(self):
        has_product_keyword = any(
            str(keyword or "").strip(" ,，、;/\n\r")
            for keyword in self.keywords
        )
        if self.industry.strip() == "其他" and not has_product_keyword:
            raise ValueError("其他类目必须填写产品关键词。")
        if self.source_type == SOURCE_TYPE_ALIBABA_1688 and not has_product_keyword:
            raise ValueError("1688采集必须填写产品关键词，系统不会自动生成默认关键词。")
        if self.source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            has_chinese_keyword = any(
                CHINESE_TEXT_PATTERN.search(str(keyword or ""))
                for keyword in self.keywords
            )
            if has_chinese_keyword:
                raise ValueError("阿里国际站关键词请使用英文产品词，避免中文关键词影响采集精准性。")
        return self


class BatchAutomationCreateDTO(TaskCreateDTO):
    batch_count: int = Field(default=8, ge=1, le=100)
    batch_collect_limit: int = Field(default=10, ge=1, le=100)
    cooldown_seconds: float = Field(default=90.0, ge=0, le=600)


class TianyanchaEnrichmentCreateDTO(BaseModel):
    task_id: str = Field(default="", max_length=64)
    limit: int = Field(default=20, ge=1, le=300)
    pacing_mode: Literal["conservative", "standard", "manual"] = "conservative"


class QixinEnrichmentCreateDTO(TianyanchaEnrichmentCreateDTO):
    pass


class ExportCreateDTO(BaseModel):
    levels: List[str] = Field(default_factory=lambda: ["A", "B"])
    is_phone_masked: bool = False
    source_type: str = Field(default="", max_length=50)
    source_group: Literal[
        "",
        "all",
        "qcc",
        "aiqicha",
        "qixin",
        "tianyancha",
        "ai_web",
        "fengniao",
        "douyin",
        "alibaba_international",
        "alibaba_tianyancha",
        "made_in_china",
        "alibaba",
    ] = ""
    industry: str = Field(default="", max_length=20)
    keyword: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=30)
    assignment_status: str = Field(default="", max_length=30)


class UsageSettingDTO(BaseModel):
    daily_quota: int = Field(default=200, ge=1, le=1000000)
    monthly_quota: int = Field(default=5000, ge=1, le=10000000)


class CollectedLeadDTO(BaseModel):
    source_type: Literal[
        "douyin_qcc",
        "qcc_public_web",
        "fengniao_public_web",
        "aiqicha_public_web",
        "qixin_public_web",
        "tianyancha_public_web",
        "ai_web_search",
        "alibaba_1688",
        "alibaba_1688_page_assistant",
        "alibaba_1688_page_import",
        "alibaba_international",
        "made_in_china_tianyancha",
    ] = SOURCE_TYPE_DOUYIN_QCC
    source_keyword: str
    industry: str
    suspected_company_name: str
    company_name_en: str = ""
    douyin_nickname: str = ""
    product_name: str = ""
    shop_level: str = ""
    contact_name: str = ""
    phone: str = ""
    phone_source: str = ""
    legal_person: str = ""
    company_status: str = ""
    unified_social_credit_code: str = ""
    business_scope: str = ""
    registered_address: str = ""
    risk_tag: str = ""
    region_text: str = ""
    website_url: str = ""
    shop_url: str = ""
    profile_url: str = ""
    sample_video_url: str = ""
    is_blue_v: bool = False
    is_enterprise_verified: bool = False
    recent_video_count_30d: int = 0
    recent_video_count_90d: int = 0
    commercial_keyword_count: int = 0


class CompanyVerifyDTO(BaseModel):
    company_name: str
    legal_person: str = ""
    company_status: str
    unified_social_credit_code: str = ""
    business_scope: str
    registered_address: str = ""
    phone: str = ""
    risk_tag: str = ""
    verification_status: str
    confidence: str
    is_success: bool = True
    failure_reason: str = ""
    consume_count: int = 1


class ScoreResultDTO(BaseModel):
    score: int
    level: str


class PageSnapshotCardDTO(BaseModel):
    text: str = Field(default="", max_length=3000)
    href: str = Field(default="", max_length=1024)


class Alibaba1688SnapshotDTO(BaseModel):
    industry: str = Field(default="服装", min_length=1, max_length=20)
    source_keyword: str = Field(default="", max_length=100)
    collect_limit: int = Field(default=30, ge=1, le=1200)
    page_url: str = Field(default="", max_length=1024)
    page_title: str = Field(default="", max_length=256)
    page_text: str = Field(default="", max_length=300000)
    cards: List[PageSnapshotCardDTO] = Field(default_factory=list, max_length=1500)
    is_qcc_enabled: bool = False
    qcc_limit: int = Field(default=0, ge=0, le=1200)


class Alibaba1688ExistenceVerificationRequestDTO(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    file_content_base64: str = Field(min_length=1)
    company_name_column_index: int = Field(default=0, ge=0, le=300)


class Alibaba1688ExistenceColumnPreviewRequestDTO(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    file_content_base64: str = Field(min_length=1)


class TianyanchaVerificationRequestDTO(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    file_content_base64: str = Field(min_length=1)
    company_name_column_index: int = Field(default=0, ge=0, le=300)
    batch_size: int = Field(default=3, ge=1, le=30)
    jitter_min_seconds: float = Field(default=8.0, ge=0, le=900)
    jitter_max_seconds: float = Field(default=22.0, ge=0, le=1200)
    batch_cooldown_seconds: float = Field(default=45.0, ge=0, le=1800)


class TianyanchaVerificationColumnPreviewRequestDTO(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    file_content_base64: str = Field(min_length=1)


class QixinVerificationRequestDTO(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    file_content_base64: str = Field(min_length=1)
    company_name_column_index: int = Field(default=0, ge=0, le=300)
    request_interval_seconds: float = Field(default=0.8, ge=0, le=60)


class QixinVerificationColumnPreviewRequestDTO(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    file_content_base64: str = Field(min_length=1)


class Alibaba1688ExistenceColumnPreviewResultDTO(BaseModel):
    headers: List[str]
    suggested_column_index: int
    suggested_column_name: str


class Alibaba1688ExistenceResultItemDTO(BaseModel):
    row_index: int
    company_name: str
    status: str
    matched_company_name: str
    search_url: str
    search_keyword: str
    remark: str
    verified_at: str


class Alibaba1688ExistenceVerificationResultDTO(BaseModel):
    job_id: str = ""
    status: str = "completed"
    processed_count: int = 0
    current_row_index: int = 0
    current_company_name: str = ""
    current_search_keyword: str = ""
    error_message: str = ""
    file_name: str
    file_path: str
    download_url: str
    exists_file_name: str
    exists_file_path: str
    exists_download_url: str
    not_exists_file_name: str
    not_exists_file_path: str
    not_exists_download_url: str
    total_count: int
    exists_count: int
    not_exists_count: int
    unconfirmed_count: int
    result_items: List[Alibaba1688ExistenceResultItemDTO] = Field(default_factory=list)


class TianyanchaVerificationResultItemDTO(BaseModel):
    row_index: int
    company_name: str
    status: str
    matched_company_name: str = ""
    legal_person: str = ""
    contact_name: str = ""
    phone: str = ""
    phone_source: str = ""
    company_status: str = ""
    unified_social_credit_code: str = ""
    registered_address: str = ""
    business_scope: str = ""
    risk_tag: str = ""
    profile_url: str = ""
    search_keyword: str = ""
    remark: str = ""
    verified_at: str = ""


class TianyanchaVerificationEventDTO(BaseModel):
    level: str
    message: str
    created_at: str


class TianyanchaVerificationResultDTO(BaseModel):
    job_id: str = ""
    status: str = "completed"
    processed_count: int = 0
    current_row_index: int = 0
    current_company_name: str = ""
    current_search_keyword: str = ""
    current_batch_index: int = 0
    total_batch_count: int = 0
    current_message: str = ""
    error_message: str = ""
    file_name: str
    file_path: str
    download_url: str
    export_file_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    total_count: int
    matched_count: int
    not_found_count: int
    unconfirmed_count: int
    batch_size: int = 3
    jitter_min_seconds: float = 8.0
    jitter_max_seconds: float = 22.0
    batch_cooldown_seconds: float = 45.0
    result_items: List[TianyanchaVerificationResultItemDTO] = Field(default_factory=list)
    event_items: List[TianyanchaVerificationEventDTO] = Field(default_factory=list)


class TianyanchaVerificationHistoryItemDTO(BaseModel):
    job_id: str = ""
    status: str = "completed"
    file_name: str = ""
    download_url: str = ""
    export_file_name: str = ""
    total_count: int = 0
    processed_count: int = 0
    matched_count: int = 0
    not_found_count: int = 0
    unconfirmed_count: int = 0
    current_message: str = ""
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""
