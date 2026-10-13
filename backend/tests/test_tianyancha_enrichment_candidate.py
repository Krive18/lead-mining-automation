import unittest
from unittest.mock import MagicMock, patch

from app.core.constant import SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB
from app.repository.lead_repository import LeadRepository
from app.model.schema import CollectedLeadDTO, TianyanchaEnrichmentCreateDTO
from app.service.collector_service import (
    EnterprisePublicWebCollector,
    ShareholderInfo,
    format_legal_shareholder_contact_name,
    normalize_shareholder_person_name,
    pick_max_person_shareholder,
)
from app.service.task_service import TaskService
from app.util.contact_name_util import normalize_contact_name


class TianyanchaEnrichmentCandidateTest(unittest.TestCase):
    def test_candidate_query_can_be_limited_to_one_alibaba_1688_task(self):
        repository = LeadRepository()
        connection = MagicMock()

        with patch("app.repository.lead_repository.get_read_connection") as connection_factory, patch(
            "app.repository.lead_repository.fetch_all"
        ) as fetch_all:
            connection_factory.return_value.__enter__.return_value = connection
            fetch_all.return_value = [
                {
                    "id": "lead-1",
                    "task_id": "task-100",
                    "source_keyword": "phone case",
                    "industry": "3C",
                    "suspected_company_name": "Example Factory",
                    "company_name": "",
                    "product_name": "phone case",
                    "phone": "",
                    "contact_name": "",
                    "legal_person": "",
                    "registered_address": "",
                }
            ]

            result = repository.list_alibaba_1688_tianyancha_enrichment_candidate(
                limit=20,
                task_id="task-100",
            )

        self.assertEqual(len(result), 1)
        query_text = fetch_all.call_args.args[1]
        query_parameters = fetch_all.call_args.args[2]
        self.assertIn("task_id = ?", query_text)
        self.assertIn("task-100", query_parameters)

    def test_enrichment_runner_uses_selected_alibaba_1688_task_id(self):
        service = TaskService.__new__(TaskService)
        service.repository = MagicMock()
        service.repository.get_task.return_value = {"collect_limit": 20}
        service.repository.list_alibaba_1688_tianyancha_enrichment_candidate.return_value = []
        service.finalize_task_status = MagicMock()

        service.run_tianyancha_enrichment_task(
            task_id="enrichment-task",
            source_task_id="task-100",
        )

        service.repository.list_alibaba_1688_tianyancha_enrichment_candidate.assert_called_once_with(
            20,
            task_id="task-100",
        )

    def test_tianyancha_enrichment_defaults_to_conservative_pacing(self):
        request = TianyanchaEnrichmentCreateDTO()
        service = TaskService.__new__(TaskService)

        profile = service.build_tianyancha_enrichment_pacing_profile(request.pacing_mode)

        self.assertEqual(request.pacing_mode, "conservative")
        self.assertEqual(profile["batch_size"], 5)
        self.assertGreaterEqual(profile["cooldown_seconds"], 180)

    def test_enrichment_runner_collects_tianyancha_in_small_batches(self):
        service = TaskService.__new__(TaskService)
        service.repository = MagicMock()
        service.repository.get_task.return_value = {"collect_limit": 6}
        service.repository.get_lead_by_id.return_value = {
            "phone": "",
            "contact_name": "",
            "legal_person": "",
            "registered_address": "",
        }
        service.repository.list_alibaba_1688_tianyancha_enrichment_candidate.return_value = [
            {
                "id": f"lead-{index}",
                "industry": "3C",
                "enrichment_company_name": f"Example Factory {index}",
            }
            for index in range(6)
        ]
        collector = MagicMock()

        def collect_batch(industry, company_name_list, collect_limit):
            return [
                CollectedLeadDTO(
                    source_type="tianyancha_public_web",
                    source_keyword=company_name,
                    industry=industry,
                    suspected_company_name=company_name,
                    registered_address="Guangdong",
                )
                for company_name in company_name_list[:collect_limit]
            ]

        collector.collect_by_company_names.side_effect = collect_batch
        service.collector_factory = MagicMock()
        service.collector_factory.get_collector.return_value = collector
        service.bind_collector_task_event_callback = MagicMock()
        service.update_alibaba_1688_lead_with_tianyancha = MagicMock()
        service.has_phone_enriched = MagicMock(return_value=False)
        service.has_contact_enriched = MagicMock(return_value=False)
        service.finalize_task_status = MagicMock()

        with patch("app.service.task_service.time.sleep") as sleep:
            service.run_tianyancha_enrichment_task(
                task_id="enrichment-task",
                source_task_id="task-100",
                pacing_mode="conservative",
            )

        self.assertEqual(collector.collect_by_company_names.call_count, 2)
        first_batch = collector.collect_by_company_names.call_args_list[0].kwargs["company_name_list"]
        second_batch = collector.collect_by_company_names.call_args_list[1].kwargs["company_name_list"]
        self.assertEqual(len(first_batch), 5)
        self.assertEqual(len(second_batch), 1)
        sleep.assert_called_once()

    def test_enrichment_runner_persists_completed_batches_when_later_batch_fails(self):
        service = TaskService.__new__(TaskService)
        service.repository = MagicMock()
        service.repository.get_task.return_value = {"collect_limit": 6}
        service.repository.get_lead_by_id.return_value = {
            "phone": "",
            "contact_name": "",
            "legal_person": "",
            "registered_address": "",
        }
        service.repository.list_alibaba_1688_tianyancha_enrichment_candidate.return_value = [
            {
                "id": f"lead-{index}",
                "task_id": "source-task",
                "industry": "3C",
                "source_keyword": "phone case",
                "enrichment_company_name": f"Example Factory {index}",
                "product_name": "phone case",
                "shop_url": f"https://factory{index}.1688.com/",
                "profile_url": f"https://factory{index}.1688.com/",
            }
            for index in range(6)
        ]
        collector = MagicMock()

        def collect_batch(industry, company_name_list, collect_limit):
            if company_name_list[0].endswith("5"):
                raise RuntimeError("risk control")
            return [
                CollectedLeadDTO(
                    source_type="tianyancha_public_web",
                    source_keyword=company_name,
                    industry=industry,
                    suspected_company_name=company_name,
                    registered_address="Guangdong",
                )
                for company_name in company_name_list[:collect_limit]
            ]

        collector.collect_by_company_names.side_effect = collect_batch
        service.collector_factory = MagicMock()
        service.collector_factory.get_collector.return_value = collector
        service.bind_collector_task_event_callback = MagicMock()
        service.update_alibaba_1688_lead_with_tianyancha = MagicMock()
        service.has_phone_enriched = MagicMock(return_value=False)
        service.has_contact_enriched = MagicMock(return_value=False)
        service.finalize_task_status = MagicMock()

        with patch("app.service.task_service.time.sleep"):
            service.run_tianyancha_enrichment_task(
                task_id="enrichment-task",
                source_task_id="task-100",
                pacing_mode="conservative",
            )

        self.assertEqual(service.update_alibaba_1688_lead_with_tianyancha.call_count, 5)
        service.repository.update_task_status.assert_any_call(
            "enrichment-task",
            "failed",
            total_count=6,
            success_count=5,
            failed_count=1,
        )

    def test_tianyancha_enrichment_keeps_product_from_1688_candidate_only(self):
        service = TaskService.__new__(TaskService)
        service.repository = MagicMock()
        service.repository.get_lead_by_id.return_value = {
            "phone": "",
            "contact_name": "",
            "legal_person": "",
            "registered_address": "",
            "product_name": "",
        }
        service.scoring_service = MagicMock()
        service.scoring_service.calculate_score.return_value = MagicMock(score=35, level="D")
        candidate = {
            "id": "lead-1",
            "task_id": "task-1",
            "source_keyword": "\u6df1\u5733\u624b\u673a\u6570\u636e\u7ebf\u5de5\u5382",
            "industry": "3C\u6570\u7801",
            "product_name": "\u624b\u673a\u6570\u636e\u7ebf",
            "shop_url": "https://factory.1688.com/",
            "profile_url": "https://factory.1688.com/",
        }
        enrichment = CollectedLeadDTO(
            source_type="tianyancha_public_web",
            source_keyword="\u6df1\u5733\u5e02\u5e38\u9752\u7535\u5b50\u7ebf\u6750\u6709\u9650\u516c\u53f8",
            industry="3C\u6570\u7801",
            suspected_company_name="\u6df1\u5733\u5e02\u5e38\u9752\u7535\u5b50\u7ebf\u6750\u6709\u9650\u516c\u53f8",
            product_name="\u7535\u5b50\u4ea7\u54c1\u9500\u552e\uff1b\u901a\u8baf\u8bbe\u5907\u9500\u552e",
            business_scope="\u7535\u5b50\u4ea7\u54c1\u9500\u552e\uff1b\u901a\u8baf\u8bbe\u5907\u9500\u552e",
            registered_address="\u6df1\u5733\u5e02",
            profile_url="https://www.tianyancha.com/company/123",
        )

        service.update_alibaba_1688_lead_with_tianyancha(candidate, enrichment)

        updated_lead_data = service.repository.update_lead_public_fields.call_args.args[1]
        self.assertEqual(updated_lead_data["product_name"], "\u624b\u673a\u6570\u636e\u7ebf")
        self.assertEqual(updated_lead_data["profile_url"], "https://factory.1688.com/")

    def test_tianyancha_does_not_auto_expand_contact_phone_by_default(self):
        collector = EnterprisePublicWebCollector.__new__(EnterprisePublicWebCollector)
        collector.source_type = SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB
        collector.config = type("Config", (), {"tianyancha_contact_expand_enabled": False})()
        page = MagicMock()

        collector.expand_contact_phone_sections(page)

        page.evaluate.assert_not_called()

    def test_shareholder_amount_unit_is_not_treated_as_person_name(self):
        self.assertEqual(normalize_contact_name("万元"), "")
        self.assertEqual(normalize_shareholder_person_name("万元"), "")
        self.assertEqual(
            format_legal_shareholder_contact_name(
                "周艳凤",
                ShareholderInfo(name="万元", share_ratio=100.0, is_person=True),
            ),
            "法人：周艳凤",
        )

    def test_pick_max_person_shareholder_ignores_amount_unit_candidate(self):
        shareholder = pick_max_person_shareholder(
            [
                ShareholderInfo(name="万元", share_ratio=90.0, is_person=True),
                ShareholderInfo(name="杨耀耀", share_ratio=10.0, is_person=True),
            ]
        )

        self.assertIsNotNone(shareholder)
        self.assertEqual(shareholder.name, "杨耀耀")


if __name__ == "__main__":
    unittest.main()
