import unittest
import unittest.mock

from pydantic import ValidationError

from app.core.constant import SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_ALIBABA_INTERNATIONAL, VERIFY_STATUS_PUBLIC_WEB
from app.model.schema import (
    BatchAutomationCreateDTO,
    CollectedLeadDTO,
    CompanyVerifyDTO,
    ScoreResultDTO,
    TaskCreateDTO,
)
from app.repository.lead_repository import SOURCE_GROUP_TYPE_MAP
from app.service.alibaba_international_collector import AlibabaInternationalSupplierCollector
from app.service.collector_service import CollectorFactory
from app.service.task_service import (
    PHONE_REQUIRED_SOURCE_TYPE_SET,
    PUBLIC_WEB_ONLY_SOURCE_TYPE_SET,
    TaskService,
)


class RecordingTaskRepository:
    def __init__(self, task=None):
        self.task = task
        self.inserted_tasks = []
        self.events = []
        self.status_updates = []
        self.inserted_leads = []

    def insert_task(self, task_data):
        self.inserted_tasks.append(task_data)

    def get_task(self, task_id):
        if self.task and self.task["id"] == task_id:
            return self.task
        return None

    def update_task_status(self, task_id, status, **kwargs):
        self.status_updates.append((task_id, status, kwargs))

    def insert_task_event(self, task_id, event_level, event_message):
        self.events.append((task_id, event_level, event_message))

    def list_lead_identity(self, source_type):
        return []

    def find_duplicate_lead_id(self, lead_data):
        return ""

    def insert_lead(self, lead_data):
        self.inserted_leads.append(lead_data)


class StubCollector:
    def __init__(self, leads, last_collect_diagnostic=""):
        self.leads = leads
        self.collect_calls = []
        self.existing_identity_list = None
        self.last_collect_diagnostic = last_collect_diagnostic

    def set_existing_lead_identity_list(self, identity_list):
        self.existing_identity_list = identity_list

    def collect(self, industry, keywords, collect_limit, target_city=""):
        self.collect_calls.append(
            {
                "industry": industry,
                "keywords": keywords,
                "collect_limit": collect_limit,
                "target_city": target_city,
            }
        )
        return self.leads


class StubCollectorFactory:
    def __init__(self, collector):
        self.collector = collector

    def get_collector(self, source_type):
        return self.collector


class GuardQccVerifier:
    def verify_company(self, company_name, industry):
        raise AssertionError("Alibaba International task must not call Qixin/QCC verifier")


class StubScoringService:
    def calculate_score(self, collected_lead, company_verify):
        return ScoreResultDTO(score=80, level="A")


class AlibabaInternationalTaskTest(unittest.TestCase):
    def build_service(self, repository=None, collector=None):
        service = TaskService.__new__(TaskService)
        service.repository = repository or RecordingTaskRepository()
        service.collector_factory = StubCollectorFactory(collector or StubCollector([]))
        service.qichacha_service = GuardQccVerifier()
        service.scoring_service = StubScoringService()
        return service

    def build_alibaba_lead(self, **overrides):
        data = {
            "source_type": SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            "source_keyword": "usb cable",
            "industry": "3C数码",
            "suspected_company_name": "Example Supplier Co., Ltd.",
            "company_name_en": "Example Supplier Co., Ltd.",
            "product_name": "USB cable",
            "company_status": "Active",
        }
        data.update(overrides)
        return CollectedLeadDTO(**data)

    def build_company_verify(self, **overrides):
        data = {
            "company_name": "Example Supplier Co., Ltd.",
            "company_status": "public",
            "business_scope": "",
            "verification_status": VERIFY_STATUS_PUBLIC_WEB,
            "confidence": "low",
            "consume_count": 0,
        }
        data.update(overrides)
        return CompanyVerifyDTO(**data)

    def test_collector_factory_returns_alibaba_international_supplier_collector(self):
        collector = CollectorFactory().get_collector(SOURCE_TYPE_ALIBABA_INTERNATIONAL)

        self.assertIsInstance(collector, AlibabaInternationalSupplierCollector)

    def test_task_service_treats_alibaba_international_as_public_web_without_phone_requirement(self):
        self.assertIn(SOURCE_TYPE_ALIBABA_INTERNATIONAL, PUBLIC_WEB_ONLY_SOURCE_TYPE_SET)
        self.assertNotIn(SOURCE_TYPE_ALIBABA_INTERNATIONAL, PHONE_REQUIRED_SOURCE_TYPE_SET)

    def test_repository_source_group_includes_alibaba_international(self):
        self.assertEqual(
            SOURCE_GROUP_TYPE_MAP["alibaba_international"],
            (SOURCE_TYPE_ALIBABA_INTERNATIONAL,),
        )

    def test_task_service_builds_alibaba_international_other_industry_task_name(self):
        service = TaskService.__new__(TaskService)

        self.assertEqual(
            service.build_task_name(SOURCE_TYPE_ALIBABA_INTERNATIONAL, "其他"),
            "阿里国际站 其他 供应商采集",
        )

    def test_create_task_normalizes_alibaba_international_qcc_options_to_disabled(self):
        repository = RecordingTaskRepository()
        service = self.build_service(repository=repository)

        service.create_task(
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_INTERNATIONAL,
                industry="3C数码",
                keywords=["usb cable"],
                collect_limit=5,
                is_qcc_enabled=True,
                qcc_limit=3,
            )
        )

        self.assertEqual(repository.inserted_tasks[0]["is_qcc_enabled"], 0)
        self.assertEqual(repository.inserted_tasks[0]["qcc_limit"], 0)

    def test_create_task_persists_alibaba_international_target_city(self):
        repository = RecordingTaskRepository()
        service = self.build_service(repository=repository)

        service.create_task(
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_INTERNATIONAL,
                industry="3C数码",
                keywords=["game controller"],
                collect_limit=5,
                target_city="东莞市",
                is_qcc_enabled=False,
                qcc_limit=0,
            )
        )

        self.assertEqual(repository.inserted_tasks[0]["target_city"], "东莞市")

    def test_create_task_persists_alibaba_international_multiple_target_cities(self):
        repository = RecordingTaskRepository()
        service = self.build_service(repository=repository)

        service.create_task(
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_INTERNATIONAL,
                industry="3C数码",
                keywords=["game controller"],
                collect_limit=5,
                target_city="广州市, 东莞市",
                is_qcc_enabled=False,
                qcc_limit=0,
            )
        )

        self.assertEqual(repository.inserted_tasks[0]["target_city"], "广州市,东莞市")

    def test_alibaba_international_rejects_chinese_keywords(self):
        with self.assertRaisesRegex(ValidationError, "阿里国际站关键词请使用英文产品词"):
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_INTERNATIONAL,
                industry="其他",
                keywords=["游戏手柄"],
                collect_limit=5,
                target_city="广东省",
                is_qcc_enabled=False,
                qcc_limit=0,
            )

    def test_create_task_persists_alibaba_1688_target_city(self):
        repository = RecordingTaskRepository()
        service = self.build_service(repository=repository)

        service.create_task(
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_1688,
                industry="服装",
                keywords=["女装批发"],
                collect_limit=5,
                target_city="佛山市",
                is_qcc_enabled=False,
                qcc_limit=0,
            )
        )

        self.assertEqual(repository.inserted_tasks[0]["target_city"], "佛山市")

    def test_create_task_persists_alibaba_1688_multiple_target_cities(self):
        repository = RecordingTaskRepository()
        service = self.build_service(repository=repository)

        service.create_task(
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_1688,
                industry="3C数码",
                keywords=["蓝牙耳机"],
                collect_limit=5,
                target_city="广州市, 东莞市",
                is_qcc_enabled=False,
                qcc_limit=0,
            )
        )

        self.assertEqual(repository.inserted_tasks[0]["target_city"], "广州市,东莞市")

    def test_alibaba_1688_rejects_empty_keywords(self):
        with self.assertRaisesRegex(ValidationError, "1688采集必须填写产品关键词"):
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_1688,
                industry="服装",
                keywords=["，"],
                collect_limit=5,
                target_city="广东省",
                is_qcc_enabled=False,
                qcc_limit=0,
            )

    def test_alibaba_international_batch_cooldown_has_same_safe_floor_as_1688(self):
        service = self.build_service()
        request = BatchAutomationCreateDTO(
            source_type=SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            industry="其他",
            keywords=["game controller"],
            target_city="广东省",
            batch_count=2,
            batch_collect_limit=10,
            cooldown_seconds=5,
            is_qcc_enabled=False,
            qcc_limit=0,
        )

        with unittest.mock.patch("app.service.task_service.random.uniform", return_value=0):
            cooldown_seconds = service.resolve_batch_cooldown_seconds(request)

        self.assertEqual(cooldown_seconds, 90.0)

    def test_run_task_saves_alibaba_international_public_leads_without_qixin_or_qcc(self):
        lead = self.build_alibaba_lead(region_text="Guangdong, China")
        task = {
            "id": "task-alibaba-international",
            "source_type": SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            "industry": "3C数码",
            "keyword_text": "usb cable",
            "collect_limit": 1,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广东省",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead])
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-international")

        self.assertEqual(len(repository.inserted_leads), 1)
        self.assertEqual(repository.inserted_leads[0]["verification_status"], VERIFY_STATUS_PUBLIC_WEB)
        self.assertEqual(collector.collect_calls[0]["collect_limit"], 1)
        self.assertEqual(collector.collect_calls[0]["target_city"], "广东省")
        event_text = "\n".join(event[2] for event in repository.events)
        self.assertIn("供应商列表", event_text)
        self.assertIn("不会自动", event_text)
        self.assertIn("启信", event_text)

    def test_run_task_passes_alibaba_international_multiple_target_cities_to_collector(self):
        lead = self.build_alibaba_lead(region_text="Guangzhou, Guangdong, China")
        task = {
            "id": "task-alibaba-international-multi-city",
            "source_type": SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            "industry": "3C数码",
            "keyword_text": "game controller",
            "collect_limit": 1,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广州市,东莞市",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead])
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-international-multi-city")

        self.assertEqual(len(repository.inserted_leads), 1)
        self.assertEqual(collector.collect_calls[0]["target_city"], "广州市,东莞市")

    def test_run_task_logs_alibaba_international_empty_diagnostic_without_phone_requirement(self):
        task = {
            "id": "task-alibaba-international-empty",
            "source_type": SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            "industry": "其他",
            "keyword_text": "silver jewelry",
            "collect_limit": 10,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "东莞市",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector(
            [],
            last_collect_diagnostic="keyword=silver jewelry; parsed_cards=0; leads=0",
        )
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-international-empty")

        event_text = "\n".join(event[2] for event in repository.events)
        self.assertIn("keyword=silver jewelry; parsed_cards=0; leads=0", event_text)
        self.assertNotIn("号码未公开", event_text)

    def test_run_task_logs_alibaba_international_partial_collection_diagnostic(self):
        lead = self.build_alibaba_lead(region_text="Guangzhou, Guangdong, China")
        task = {
            "id": "task-alibaba-international-partial",
            "source_type": SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            "industry": "其他",
            "keyword_text": "silver jewelry",
            "collect_limit": 10,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广州市",
        }
        diagnostic = (
            "keyword=silver jewelry; parsed_cards=42; leads=1; pages=4; "
            "existing_skips=39; repeated_pages=1"
        )
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead], last_collect_diagnostic=diagnostic)
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-international-partial")

        event_text = "\n".join(event[2] for event in repository.events)
        self.assertIn(diagnostic, event_text)

    def test_run_task_passes_alibaba_1688_target_city_to_collector(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            source_keyword="佛山女装批发",
            industry="服装",
            suspected_company_name="佛山市示例服装有限公司",
            product_name="女装批发",
            phone="未公开",
            phone_source="1688搜索页未展示公开电话",
            region_text="佛山 超级工厂 女装批发",
        )
        task = {
            "id": "task-alibaba-1688",
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "industry": "服装",
            "keyword_text": "女装批发",
            "collect_limit": 1,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "佛山市",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead])
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-1688")

        self.assertEqual(len(repository.inserted_leads), 1)
        self.assertEqual(collector.collect_calls[0]["target_city"], "佛山市")

    def test_run_task_passes_alibaba_1688_multiple_target_cities_to_collector(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            source_keyword="广州蓝牙耳机",
            industry="3C数码",
            suspected_company_name="广州市示例电子有限公司",
            product_name="蓝牙耳机",
            phone="未公开",
            phone_source="1688搜索页未展示公开电话",
            region_text="广州 超级工厂 蓝牙耳机",
        )
        task = {
            "id": "task-alibaba-1688-multi-city",
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "industry": "3C数码",
            "keyword_text": "蓝牙耳机",
            "collect_limit": 1,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广州市,东莞市",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead])
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-1688-multi-city")

        self.assertEqual(len(repository.inserted_leads), 1)
        self.assertEqual(collector.collect_calls[0]["target_city"], "广州市,东莞市")

    def test_run_task_logs_alibaba_1688_partial_collect_diagnostic(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            source_keyword="蓝牙耳机",
            industry="3C数码",
            suspected_company_name="广州市示例电子有限公司",
            product_name="蓝牙耳机",
            phone="未公开",
            phone_source="1688搜索页未展示公开电话",
            region_text="广州 超级工厂 蓝牙耳机",
        )
        task = {
            "id": "task-alibaba-1688-partial",
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "industry": "3C数码",
            "keyword_text": "蓝牙耳机",
            "collect_limit": 50,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广州市",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead], last_collect_diagnostic="1688本次只采集到 1/50 条公开线索；已存在/重复线索 12 条。")
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-1688-partial")

        event_text = "\n".join(event[2] for event in repository.events)
        self.assertIn("1688本次只采集到 1/50", event_text)

    def test_run_task_keeps_alibaba_1688_empty_product_instead_of_keyword_fallback(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            source_keyword="广东游戏键盘",
            industry="其他",
            suspected_company_name="深圳市锐锋电子有限公司",
            product_name="",
            phone="未公开",
            phone_source="1688搜索页未展示公开电话",
            region_text="深圳 超级工厂 96%履约率",
        )
        task = {
            "id": "task-alibaba-1688-empty-product",
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "industry": "其他",
            "keyword_text": "游戏键盘",
            "collect_limit": 1,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广东省",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector([lead])
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-1688-empty-product")

        self.assertEqual(len(repository.inserted_leads), 1)
        self.assertEqual(repository.inserted_leads[0]["product_name"], "")

    def test_run_task_keeps_alibaba_1688_search_page_results_for_selected_city(self):
        lead_list = [
            CollectedLeadDTO(
                source_type=SOURCE_TYPE_ALIBABA_1688,
                source_keyword="广州蓝牙耳机",
                industry="3C数码",
                suspected_company_name="广州市目标电子有限公司",
                product_name="蓝牙耳机",
                phone="未公开",
                phone_source="1688搜索页未展示公开电话",
                region_text="广州市目标电子有限公司 广州 超级工厂 蓝牙耳机",
            ),
            CollectedLeadDTO(
                source_type=SOURCE_TYPE_ALIBABA_1688,
                source_keyword="广州蓝牙耳机",
                industry="3C数码",
                suspected_company_name="深圳市外部电子有限公司",
                product_name="蓝牙耳机",
                phone="未公开",
                phone_source="1688搜索页未展示公开电话",
                region_text="深圳市外部电子有限公司 深圳 超级工厂 蓝牙耳机",
            ),
        ]
        task = {
            "id": "task-alibaba-1688-city-filter",
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "industry": "3C数码",
            "keyword_text": "蓝牙耳机",
            "collect_limit": 2,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广州市",
        }
        repository = RecordingTaskRepository(task=task)
        collector = StubCollector(lead_list)
        service = self.build_service(repository=repository, collector=collector)

        service.run_task("task-alibaba-1688-city-filter")

        self.assertEqual(len(repository.inserted_leads), 2)
        self.assertEqual(
            [lead["suspected_company_name"] for lead in repository.inserted_leads],
            ["广州市目标电子有限公司", "深圳市外部电子有限公司"],
        )
        event_text = "\n".join(event[2] for event in repository.events)
        self.assertNotIn("地区不符", event_text)

    def test_target_city_filter_skips_second_pass_for_alibaba_1688_search_results(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            source_keyword="广州蓝牙音箱",
            industry="3C数码",
            suspected_company_name="星河声学科技有限公司",
            product_name="蓝牙音箱",
            phone="未公开",
            phone_source="1688搜索页未展示公开电话",
            region_text="超级工厂 蓝牙音箱 65%回头率",
        )
        task = {
            "id": "task-alibaba-1688-source-keyword-filter",
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "industry": "3C数码",
            "keyword_text": "蓝牙音箱",
            "collect_limit": 1,
            "is_qcc_enabled": 0,
            "qcc_limit": 0,
            "target_city": "广州市",
        }
        service = self.build_service(repository=RecordingTaskRepository(task=task), collector=StubCollector([lead]))

        reason = service.get_target_region_disqualified_reason(task, lead, self.build_company_verify(company_name=""))

        self.assertEqual(reason, "")

    def test_alibaba_international_target_city_region_text_uses_english_city_token(self):
        service = self.build_service()

        self.assertTrue(
            service.is_alibaba_international_target_city_region_text(
                "Dongguan, Guangdong, China",
                ["东莞"],
            )
        )
        self.assertFalse(
            service.is_alibaba_international_target_city_region_text(
                "Shenzhen, Guangdong, China",
                ["东莞"],
            )
        )

    def test_build_lead_data_extracts_city_from_english_company_name_parentheses(self):
        service = self.build_service()
        company_name = "Quanhang Supply Chain Management (guangzhou) Co., Ltd."
        lead = self.build_alibaba_lead(
            suspected_company_name=company_name,
            company_name_en=company_name,
            region_text="",
        )

        lead_data = service.build_lead_data(
            "task-alibaba-international-city",
            lead,
            self.build_company_verify(company_name=""),
            ScoreResultDTO(score=80, level="A"),
        )

        self.assertEqual(lead_data["province"], "广东省")
        self.assertEqual(lead_data["city"], "广州")
        self.assertEqual(lead_data["city_source"], "公司名称")
        self.assertEqual(lead_data["city_confidence"], "medium")

    def test_alibaba_international_guangdong_accepts_region_text_or_province_evidence(self):
        service = self.build_service()

        self.assertTrue(
            service.is_guangdong_lead(
                self.build_alibaba_lead(region_text="Guangdong, China"),
                self.build_company_verify(),
            )
        )
        self.assertTrue(
            service.is_guangdong_lead(
                self.build_alibaba_lead(registered_address="广东省深圳市南山区测试路1号"),
                self.build_company_verify(),
            )
        )

    def test_alibaba_international_guangdong_rejects_inferred_or_unrelated_evidence(self):
        service = self.build_service()

        false_positive_cases = [
            (
                self.build_alibaba_lead(
                    suspected_company_name="Guangdong Example Supplier Co., Ltd.",
                    company_name_en="Guangdong Example Supplier Co., Ltd.",
                ),
                self.build_company_verify(),
            ),
            (
                self.build_alibaba_lead(profile_url="https://example.com/广东/supplier"),
                self.build_company_verify(),
            ),
            (
                self.build_alibaba_lead(business_scope="主营产品覆盖广东省跨境渠道"),
                self.build_company_verify(),
            ),
            (
                self.build_alibaba_lead(region_text="Zhejiang, China"),
                self.build_company_verify(
                    company_name="广东测试科技有限公司",
                    registered_address="广东省深圳市南山区测试路1号",
                    business_scope="广东省内销售",
                ),
            ),
        ]

        for lead, company_verify in false_positive_cases:
            with self.subTest(lead=lead):
                self.assertFalse(service.is_guangdong_lead(lead, company_verify))


if __name__ == "__main__":
    unittest.main()
