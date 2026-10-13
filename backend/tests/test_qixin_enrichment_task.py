import unittest
from unittest.mock import Mock

from app.core.constant import SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_QIXIN_PUBLIC_WEB, TASK_STATUS_COLLECTING
from app.model.schema import CollectedLeadDTO, QixinEnrichmentCreateDTO
from app.service.qixin_api_service import QixinApiError, QixinApiService, QixinCompanyResult
from app.service.task_service import TaskService


class QixinEnrichmentTaskTest(unittest.TestCase):
    def test_create_qixin_enrichment_task_targets_selected_1688_batch(self):
        service = TaskService.__new__(TaskService)
        service.repository = Mock()
        service.repository.get_task.return_value = {"source_type": SOURCE_TYPE_ALIBABA_1688}
        service.qixin_api_service = Mock(spec=QixinApiService, unsafe=True)
        request = QixinEnrichmentCreateDTO(task_id="source-task-001", limit=12)

        task_id = service.create_qixin_enrichment_task(request)

        self.assertTrue(task_id)
        service.qixin_api_service.assert_configured.assert_called_once_with()
        inserted_task = service.repository.insert_task.call_args.args[0]
        self.assertEqual(inserted_task["source_type"], SOURCE_TYPE_QIXIN_PUBLIC_WEB)
        self.assertEqual(inserted_task["collect_limit"], 12)

    def test_qixin_runner_persists_each_successful_company(self):
        service = TaskService.__new__(TaskService)
        service.repository = Mock()
        service.repository.get_task.return_value = {
            "collect_limit": 1,
            "status": TASK_STATUS_COLLECTING,
        }
        candidate = {
            "id": "lead-001",
            "task_id": "source-task-001",
            "source_keyword": "游戏手柄",
            "industry": "其他",
            "product_name": "游戏手柄",
            "enrichment_company_name": "深圳市测试科技有限公司",
            "shop_url": "https://test.1688.com/",
            "profile_url": "https://test.1688.com/",
        }
        service.repository.list_alibaba_1688_tianyancha_enrichment_candidate.return_value = [candidate]
        service.qixin_api_service = Mock()
        service.qixin_api_service.query_company.return_value = QixinCompanyResult(
            lead=CollectedLeadDTO(
                source_type=SOURCE_TYPE_QIXIN_PUBLIC_WEB,
                source_keyword="深圳市测试科技有限公司",
                industry="其他",
                suspected_company_name="深圳市测试科技有限公司",
                legal_person="李四",
                phone="13812349876",
                unified_social_credit_code="91440300MA5F12345X",
                registered_address="广东省深圳市南山区测试路1号",
            ),
            endpoint_status={
                "basic": {"success": True},
                "contact": {"success": True},
                "partners": {"success": True},
            },
        )
        service.update_alibaba_1688_lead_with_tianyancha = Mock()
        service.finalize_task_status = Mock()

        service.run_qixin_enrichment_task("qixin-task-001", "source-task-001")

        service.qixin_api_service.query_company.assert_called_once_with(
            "深圳市测试科技有限公司",
            "其他",
        )
        service.update_alibaba_1688_lead_with_tianyancha.assert_called_once_with(
            candidate,
            service.qixin_api_service.query_company.return_value.lead,
        )
        service.finalize_task_status.assert_called_once()
        finalize_kwargs = service.finalize_task_status.call_args.kwargs
        self.assertEqual(finalize_kwargs["success_count"], 1)
        self.assertEqual(finalize_kwargs["failed_count"], 0)

    def test_qixin_runner_stops_remaining_calls_after_authorization_failure(self):
        service = TaskService.__new__(TaskService)
        service.repository = Mock()
        service.repository.get_task.return_value = {
            "collect_limit": 2,
            "status": TASK_STATUS_COLLECTING,
        }
        service.repository.list_alibaba_1688_tianyancha_enrichment_candidate.return_value = [
            {
                "id": "lead-001",
                "industry": "其他",
                "enrichment_company_name": "深圳市测试一有限公司",
            },
            {
                "id": "lead-002",
                "industry": "其他",
                "enrichment_company_name": "深圳市测试二有限公司",
            },
        ]
        service.qixin_api_service = Mock()
        service.qixin_api_service.query_company.side_effect = QixinApiError(
            "未添加IP白名单",
            endpoint="/enterprise/getBasicInfo",
            status="104",
        )
        service.qixin_api_service.get_connection_status.return_value = {
            "configured": True,
            "egress_ip": "14.145.79.63",
            "egress_region": "中国 广东 广州 电信",
        }

        service.run_qixin_enrichment_task("qixin-task-001", "source-task-001")

        service.qixin_api_service.query_company.assert_called_once()
        failed_updates = [
            call for call in service.repository.update_task_status.call_args_list
            if len(call.args) > 1 and call.args[1] == "failed"
        ]
        self.assertTrue(failed_updates)
        self.assertEqual(failed_updates[-1].kwargs["failed_count"], 2)
        event_text = "\n".join(call.args[2] for call in service.repository.insert_task_event.call_args_list)
        self.assertIn("14.145.79.63", event_text)


if __name__ == "__main__":
    unittest.main()
