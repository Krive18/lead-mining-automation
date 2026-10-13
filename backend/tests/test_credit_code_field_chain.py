import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.database import init_database
from app.repository.lead_repository import LeadRepository


class CreditCodeFieldChainTest(unittest.TestCase):
    def test_repository_persists_and_reads_unified_social_credit_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(
                database_driver="sqlite",
                database_path=Path(temp_dir) / "credit-code.db",
            )
            with patch("app.core.database.get_config", return_value=config):
                init_database()
                repository = LeadRepository()
                repository.insert_lead(
                    {
                        "id": "lead-credit-code",
                        "task_id": "task-credit-code",
                        "source_type": "tianyancha_public_web",
                        "source_keyword": "广州测试有限公司",
                        "industry": "美妆个护",
                        "suspected_company_name": "广州测试有限公司",
                        "company_name": "广州测试有限公司",
                        "douyin_nickname": "",
                        "product_name": "美甲用品",
                        "contact_name": "",
                        "phone": "",
                        "phone_source": "",
                        "website_url": "",
                        "shop_url": "",
                        "profile_url": "",
                        "sample_video_url": "",
                        "is_blue_v": 0,
                        "is_enterprise_verified": 1,
                        "company_status": "存续",
                        "unified_social_credit_code": "91440101MA5CKX7R2L",
                        "legal_person": "张三",
                        "business_scope": "美甲用品销售",
                        "registered_address": "广东省广州市天河区测试路1号",
                        "province": "广东省",
                        "city": "广州市",
                        "district": "天河区",
                        "city_source": "企业地址",
                        "city_confidence": "high",
                        "risk_tag": "",
                        "verification_status": "public_web",
                        "confidence": "high",
                        "score": 80,
                        "level": "A",
                        "assignment_status": "unassigned",
                        "gmt_create": "2026-07-10 10:00:00",
                        "gmt_modified": "2026-07-10 10:00:00",
                    }
                )

                lead = repository.get_lead_by_id("lead-credit-code")

            self.assertEqual(lead["unified_social_credit_code"], "91440101MA5CKX7R2L")


if __name__ == "__main__":
    unittest.main()
