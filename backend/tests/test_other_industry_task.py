import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from app.core.constant import SOURCE_TYPE_ALIBABA_1688
from app.model.schema import TaskCreateDTO
from app.service.task_service import TaskService


class OtherIndustryTaskTest(unittest.TestCase):
    def setUp(self):
        self.service = TaskService.__new__(TaskService)

    def test_other_industry_is_preserved(self):
        self.assertEqual(self.service.normalize_industry("其他"), "其他")

    def test_other_industry_uses_only_supplied_keywords(self):
        keyword_list = self.service.normalize_keyword(
            ["手持蒸汽熨烫机,游戏手柄"],
            "其他",
            SOURCE_TYPE_ALIBABA_1688,
        )

        self.assertEqual(keyword_list, ["手持蒸汽熨烫机", "游戏手柄"])

    def test_other_industry_requires_a_product_keyword(self):
        with self.assertRaisesRegex(ValueError, "其他类目必须填写产品关键词"):
            self.service.normalize_keyword([], "其他", SOURCE_TYPE_ALIBABA_1688)

    def test_other_industry_request_rejects_blank_keywords(self):
        with self.assertRaises(ValidationError) as error_context:
            TaskCreateDTO(
                source_type=SOURCE_TYPE_ALIBABA_1688,
                industry="其他",
                keywords=["，"],
            )
        error_text = str(error_context.exception)
        self.assertIn("其他类目必须填写产品关键词", error_text)
        self.assertNotIn("手持蒸汽熨烫机", error_text)
        self.assertNotIn("游戏手柄", error_text)

    def test_other_industry_ai_task_does_not_expand_user_keywords(self):
        service = TaskService.__new__(TaskService)
        service.deepseek_ai_service = Mock()
        service.deepseek_ai_service.is_enabled.return_value = True
        service.create_task = Mock(return_value="task-other-001")
        service.repository = Mock()
        request = TaskCreateDTO(
            source_type=SOURCE_TYPE_ALIBABA_1688,
            industry="其他",
            keywords=["手持蒸汽熨烫机", "游戏手柄"],
        )

        task_id = service.create_ai_lead_discovery_task(request)

        self.assertEqual(task_id, "task-other-001")
        service.deepseek_ai_service.build_lead_discovery_keywords.assert_not_called()
        created_request = service.create_task.call_args.args[0]
        self.assertEqual(created_request.industry, "其他")
        self.assertEqual(created_request.keywords, ["手持蒸汽熨烫机", "游戏手柄"])


if __name__ == "__main__":
    unittest.main()
