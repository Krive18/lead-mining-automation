import unittest

from app.core.constant import SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA
from app.model.schema import CollectedLeadDTO, TaskCreateDTO
from app.repository.lead_repository import SOURCE_GROUP_TYPE_MAP
from app.service.export_service import TIANYANCHA_EXPORT_SOURCE_TYPE_SET
from app.service.task_service import (
    PHONE_REQUIRED_SOURCE_TYPE_SET,
    PUBLIC_WEB_ONLY_SOURCE_TYPE_SET,
    TaskService,
)


class MadeInChinaSourceTypeTest(unittest.TestCase):
    def test_task_create_accepts_made_in_china_source_type(self):
        request = TaskCreateDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            industry="3C数码",
            keywords=["手机壳工厂"],
            collect_limit=5,
            is_qcc_enabled=False,
            qcc_limit=0,
        )
        self.assertEqual(request.source_type, "made_in_china_tianyancha")

    def test_collected_lead_accepts_made_in_china_source_type(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword="手机壳工厂",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
        )
        self.assertEqual(lead.source_type, SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)

    def test_task_service_treats_made_in_china_as_public_web_source(self):
        service = TaskService.__new__(TaskService)
        self.assertIn(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, PUBLIC_WEB_ONLY_SOURCE_TYPE_SET)
        self.assertIn(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, PHONE_REQUIRED_SOURCE_TYPE_SET)
        self.assertEqual(
            service.build_task_name(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, "3C数码"),
            "中国制造网+天眼查 3C数码 线索采集",
        )

    def test_repository_and_export_source_groups_include_made_in_china(self):
        self.assertEqual(
            SOURCE_GROUP_TYPE_MAP["made_in_china"],
            (SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,),
        )
        self.assertIn(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, TIANYANCHA_EXPORT_SOURCE_TYPE_SET)

    def test_task_service_exposes_made_in_china_warmup(self):
        service = TaskService.__new__(TaskService)
        self.assertTrue(callable(getattr(service, "start_made_in_china_warmup")))


if __name__ == "__main__":
    unittest.main()
