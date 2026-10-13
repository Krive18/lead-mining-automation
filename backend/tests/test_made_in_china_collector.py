import unittest

from app.core.constant import SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB
from app.model.schema import CollectedLeadDTO
from app.service.collector_service import (
    CollectorFactory,
    MadeInChinaPublicPageCollector,
    MadeInChinaTianyanchaCollector,
)


class FakeMadeInChinaCollector:
    def __init__(self, lead_list):
        self.lead_list = lead_list
        self.existing_identity_list = []
        self.task_event_callback = None

    def set_task_event_callback(self, callback):
        self.task_event_callback = callback

    def set_existing_lead_identity_list(self, identity_list):
        self.existing_identity_list = identity_list

    def collect(self, industry, keywords, collect_limit):
        return self.lead_list[:collect_limit]


class FakeTianyanchaCollector:
    def __init__(self, lead_list=None, error=None):
        self.lead_list = lead_list or []
        self.error = error
        self.requested_company_name_list = []
        self.task_event_callback = None

    def set_task_event_callback(self, callback):
        self.task_event_callback = callback

    def collect_by_company_names(self, industry, company_name_list, collect_limit):
        self.requested_company_name_list = list(company_name_list)
        if self.error is not None:
            raise self.error
        return self.lead_list[:collect_limit]


class MadeInChinaPublicPageCollectorTest(unittest.TestCase):
    def test_search_keyword_list_keeps_user_terms_and_defaults(self):
        collector = MadeInChinaPublicPageCollector()

        keyword_list = collector.build_search_keyword_list("3C数码", ["手机壳工厂"])

        self.assertIn("手机壳工厂", keyword_list)
        self.assertEqual(len(keyword_list), len(set(keyword_list)))
        self.assertTrue(collector.build_search_keyword_list("3C数码", []))

    def test_search_url_uses_real_product_result_path(self):
        collector = MadeInChinaPublicPageCollector()

        search_url = collector.build_search_url("手机壳工厂", 1)

        self.assertIn("/productdirectory.do", search_url)
        self.assertNotIn("/companysearch.do", search_url)
        self.assertIn("newCn=1", search_url)
        self.assertIn("comProvince=Guangdong", search_url)
        self.assertNotIn("comProvince=nolimit", search_url)

    def test_build_candidate_extracts_company_name_from_company_card(self):
        collector = MadeInChinaPublicPageCollector()

        candidate = collector.build_candidate(
            "手机壳工厂",
            {
                "href": "https://example.cn.made-in-china.com/",
                "text": "佛山市贝丽思电子科技有限公司",
                "title": "TPU手机壳厂家",
                "parentText": "主营产品：TPU手机壳 手机保护壳 公司地址：广东省佛山市南海区 经营模式：生产制造",
            },
            "3C数码",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "佛山市贝丽思电子科技有限公司")
        self.assertIn("手机壳", candidate.product_name)
        self.assertEqual(candidate.region_text, "广东省佛山市南海区")

    def test_build_candidate_prefers_company_info_link_company_name(self):
        collector = MadeInChinaPublicPageCollector()

        candidate = collector.build_candidate(
            "手机壳工厂",
            {
                "href": "https://cn.made-in-china.com/showroom/b13560121395-companyinfo.html",
                "text": "第 1 年 生产制造",
                "title": "",
                "companyName": "佛山市贝耐思电子科技有限公司",
                "parentText": (
                    "会员注册：第 1 年 经营模式：生产制造 成立日期：2020-06-01 "
                    "供应产品：20 条 面议 哪里有专门做凯夫拉水贴工艺的手机壳工厂？ "
                    "佛山市贝耐思电子科技有限公司 广东省 佛山市"
                ),
            },
            "3C数码",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "佛山市贝耐思电子科技有限公司")
        self.assertEqual(
            candidate.profile_url,
            "https://cn.made-in-china.com/showroom/b13560121395-companyinfo.html",
        )

    def test_build_candidate_skips_login_actions_and_non_company_text(self):
        collector = MadeInChinaPublicPageCollector()

        candidate = collector.build_candidate(
            "手机壳工厂",
            {
                "href": "https://membercenter.cn.made-in-china.com/login/",
                "text": "在线交谈 发联系信 发布询价单",
                "title": "",
                "parentText": "登录后继续",
            },
            "3C数码",
        )

        self.assertIsNone(candidate)

    def test_build_lead_from_candidate_uses_made_in_china_source_type(self):
        collector = MadeInChinaPublicPageCollector()
        candidate = collector.build_candidate(
            "手机壳工厂",
            {
                "href": "https://example.cn.made-in-china.com/",
                "text": "佛山市贝丽思电子科技有限公司",
                "title": "TPU手机壳厂家",
                "parentText": "主营产品：TPU手机壳 广东省佛山市南海区 经营模式：生产制造",
            },
            "3C数码",
        )

        lead = collector.build_lead_from_candidate(candidate, "3C数码")

        self.assertEqual(lead.source_type, SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)
        self.assertEqual(lead.suspected_company_name, "佛山市贝丽思电子科技有限公司")
        self.assertEqual(lead.phone, "")


class MadeInChinaTianyanchaCollectorTest(unittest.TestCase):
    def test_factory_returns_made_in_china_tianyancha_collector(self):
        collector = CollectorFactory().get_collector(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)

        self.assertIsInstance(collector, MadeInChinaTianyanchaCollector)

    def test_collect_enriches_company_names_with_tianyancha_fields(self):
        made_in_china_lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword="手机壳工厂",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
            product_name="TPU手机壳",
            profile_url="https://example.cn.made-in-china.com/",
            region_text="中国制造网 华南 广东 佛山",
        )
        tianyancha_lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
            source_keyword="佛山市贝丽思电子科技有限公司",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
            contact_name="",
            phone="13912345678",
            phone_source="天眼查公开页",
            legal_person="张三",
            company_status="存续",
            registered_address="广东省佛山市南海区工业园",
            business_scope="生产、销售：手机保护壳",
            region_text="天眼查 广东 佛山",
            is_enterprise_verified=True,
        )
        made_in_china_collector = FakeMadeInChinaCollector([made_in_china_lead])
        tianyancha_collector = FakeTianyanchaCollector([tianyancha_lead])
        collector = MadeInChinaTianyanchaCollector(
            made_in_china_collector=made_in_china_collector,
            tianyancha_collector=tianyancha_collector,
        )

        result_list = collector.collect("3C数码", ["手机壳工厂"], 5)

        self.assertEqual(tianyancha_collector.requested_company_name_list, ["佛山市贝丽思电子科技有限公司"])
        self.assertEqual(len(result_list), 1)
        result = result_list[0]
        self.assertEqual(result.source_type, SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)
        self.assertEqual(result.phone, "13912345678")
        self.assertEqual(result.contact_name, "张三")
        self.assertEqual(result.legal_person, "张三")
        self.assertEqual(result.company_status, "存续")
        self.assertEqual(result.registered_address, "广东省佛山市南海区工业园")
        self.assertTrue(result.is_enterprise_verified)

    def test_collect_keeps_made_in_china_leads_when_tianyancha_fails(self):
        made_in_china_lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword="手机壳工厂",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
        )
        collector = MadeInChinaTianyanchaCollector(
            made_in_china_collector=FakeMadeInChinaCollector([made_in_china_lead]),
            tianyancha_collector=FakeTianyanchaCollector(error=RuntimeError("blocked")),
        )

        result_list = collector.collect("3C数码", ["手机壳工厂"], 5)

        self.assertEqual(result_list, [made_in_china_lead])


if __name__ == "__main__":
    unittest.main()
