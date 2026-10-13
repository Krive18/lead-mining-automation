import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock, patch

from app.service.collector_service import (
    Alibaba1688TianyanchaCollector,
    AlibabaCandidate,
    Alibaba1688PublicPageCollector,
    ALIBABA_1688_LOGIN_URL,
    BrowserSession,
    PlaywrightTimeoutError,
    build_jittered_milliseconds,
    clean_company_name_text,
)
from app.model.schema import CollectedLeadDTO


class Alibaba1688CollectorTest(unittest.TestCase):
    def test_build_candidate_uses_precise_card_category_as_product_name(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://flyita.1688.com/",
            "text": "\u6df1\u5733\u5e02\u98de\u4ebf\u8fbe\u670d\u88c5\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u6df1\u5733\u5e02\u98de\u4ebf\u8fbe\u670d\u88c5\u6709\u9650\u516c\u53f8 "
                "\u6df1\u5733 \u8d85\u7ea7\u5de5\u5382 \u8bda21\u5e74 | "
                "\u5de5\u88c5\u3001\u5236\u670d\u52a1Polo\u886b \u7537\u5f0f\u536b\u8863 | "
                "2477m\u00b2 | 101-500\u4eba "
                "\u91d1\u724c\u5236\u9020 93%\u54cd\u5e94\u7387 96%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            raw_item,
            "\u670d\u88c5",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.product_name, "\u5de5\u88c5\u3001\u5236\u670d\u52a1Polo\u886b\u3001\u7537\u5f0f\u536b\u8863")

    def test_build_candidate_uses_category_when_card_has_no_pipe_separator(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://xinsheng.1688.com/",
            "text": "\u897f\u5b89",
            "title": "",
            "parentText": (
                "\u666e\u5b81\u5e02\u6b23\u76db\u670d\u88c5\u5382 \u63ed\u9633 "
                "\u8d85\u7ea7\u5de5\u5382 \u8bda2\u5e74 "
                "\u5973\u58eb\u5bb6\u5c45\u670d \u7ae5\u5bb6\u5c45\u670d\u5957\u88c5 "
                "\u7761\u888d\u3001\u6d74\u888d 1755m\u00b2 101-500\u4eba "
                "\u91d1\u724c\u5236\u9020 72%\u54cd\u5e94\u7387 100%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            raw_item,
            "\u670d\u88c5",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.product_name,
            "\u5973\u58eb\u5bb6\u5c45\u670d\u3001\u7ae5\u5bb6\u5c45\u670d\u5957\u88c5\u3001\u7761\u888d\u3001\u6d74\u888d",
        )

    def test_build_candidate_rejects_year_as_product_when_category_exists(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://duojiao.1688.com/",
            "text": "9\u5e74",
            "title": "",
            "parentText": (
                "\u6df1\u5733\u5e02\u771f\u591a\u5a07\u670d\u88c5\u6709\u9650\u516c\u53f8 \u63ed\u9633 "
                "\u8d85\u7ea7\u5de5\u5382 \u8bda3\u5e74 "
                "\u5973\u58eb\u5bb6\u5c45\u670d \u7761\u88d9 \u60c5\u4fa3\u5bb6\u5c45\u670d "
                "2000m\u00b2 10\u4eba\u4ee5\u4e0b "
                "\u91d1\u724c\u5236\u9020 87%\u54cd\u5e94\u7387 100%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            raw_item,
            "\u670d\u88c5",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.product_name,
            "\u5973\u58eb\u5bb6\u5c45\u670d\u3001\u7761\u88d9\u3001\u60c5\u4fa3\u5bb6\u5c45\u670d",
        )

    def test_build_candidate_keeps_category_when_factory_display_name_has_no_suffix(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://yibo.1688.com/",
            "text": "\u4e1c\u839e\u5e02\u864e\u95e8\u4ea6\u535a\u670d\u9970",
            "title": "",
            "parentText": (
                "\u4e1c\u839e\u5e02\u864e\u95e8\u4ea6\u535a\u670d\u9970 \u4e1c\u839e "
                "\u8bda2\u5e74 | \u8fde\u8863\u88d9 \u5973\u5f0fT\u6064 "
                "\u5927\u7801\u8fde\u8863\u88d9 | 96%\u54cd\u5e94\u7387 | "
                "100%\u5c65\u7ea6\u7387 | 55%\u56de\u5934\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u4e1c\u839e\u670d\u88c5\u5de5\u5382",
            raw_item,
            "\u670d\u88c5",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "\u4e1c\u839e\u5e02\u864e\u95e8\u4ea6\u535a\u670d\u9970")
        self.assertEqual(candidate.product_name, "\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064\u3001\u5927\u7801\u8fde\u8863\u88d9")

    def test_build_candidate_does_not_use_search_keyword_as_product_name(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://example.1688.com/",
            "text": "\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde \u8d85\u7ea7\u5de5\u5382 \u8bda2\u5e74 "
                "2500m\u00b2 90\u5458\u5de5 96%\u54cd\u5e94\u7387 100%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            raw_item,
            "\u670d\u88c5",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.product_name, "")

    def test_build_candidate_keeps_visible_company_even_when_city_text_differs(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://shenzhen-audio.1688.com/",
            "text": "深圳市外部电子有限公司",
            "title": "",
            "parentText": "深圳市外部电子有限公司 深圳 超级工厂 蓝牙音箱 96%响应率",
        }

        candidate = collector.build_candidate(
            "广州蓝牙音箱",
            raw_item,
            "3C数码",
            target_city="广州市",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "深圳市外部电子有限公司")
        self.assertEqual(candidate.product_name, "蓝牙音箱")

    def test_build_candidate_keeps_visible_company_without_keyword_relevance_filter(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://skin-care.1688.com/",
            "text": "广州市样例日化有限公司",
            "title": "",
            "parentText": "广州市样例日化有限公司 广州 超级工厂 护肤品 化妆水 96%响应率",
        }

        candidate = collector.build_candidate(
            "广州蓝牙音箱",
            raw_item,
            "3C数码",
            target_city="广州市",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "广州市样例日化有限公司")
        self.assertEqual(candidate.product_name, "护肤品、化妆水")

    def test_build_candidate_prefers_full_card_category_over_anchor_text(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://laxue.1688.com/",
            "text": "\u7f8e\u5986\u86cb",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u83b1\u96ea\u5316\u5986\u7528\u54c1\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde\u5e02 \u7c89\u6251\u3001\u7f8e\u5986\u86cb "
                "\u6d17\u8138\u6251 \u5176\u4ed6\u7f8e\u5986\u5de5\u5177 "
                "7%\u54cd\u5e94\u7387 \u751f\u4ea7\u5b9e\u529b\u5f3a\uff0c"
                "3CE\u4f9b\u5e94\u5546 3CE\u4ee3\u5de5 \u652f\u6301\u8d34\u724c\u52a0\u5de5"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u7f8e\u5986\u86cb\u5de5\u5382",
            raw_item,
            "\u7f8e\u5986\u4e2a\u62a4",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.product_name,
            "\u7c89\u6251\u3001\u7f8e\u5986\u86cb\u3001\u6d17\u8138\u6251\u3001\u5176\u4ed6\u7f8e\u5986\u5de5\u5177",
        )

    def test_build_candidate_prefers_browser_category_text(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://liren.1688.com/",
            "text": "\u7f8e\u5986\u86cb",
            "title": "",
            "categoryText": "\u7c89\u6251\u3001\u7f8e\u5986\u86cb \u6d17\u8138\u6251 \u5176\u4ed6\u7f8e\u5986\u5de5\u5177",
            "parentText": (
                "\u5e7f\u5dde\u7f8e\u5986\u86cb\u5de5\u5382 \u641c\u7d22 "
                "\u4e3d\u7814\u5316\u5986\u7528\u54c1(\u4e1c\u839e)\u6709\u9650\u516c\u53f8 "
                "\u4e1c\u839e 45%\u54cd\u5e94\u7387 100%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u7f8e\u5986\u86cb\u5de5\u5382",
            raw_item,
            "\u7f8e\u5986\u4e2a\u62a4",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "\u4e3d\u7814\u5316\u5986\u7528\u54c1(\u4e1c\u839e)\u6709\u9650\u516c\u53f8")
        self.assertEqual(
            candidate.product_name,
            "\u7c89\u6251\u3001\u7f8e\u5986\u86cb\u3001\u6d17\u8138\u6251\u3001\u5176\u4ed6\u7f8e\u5986\u5de5\u5177",
        )

    def test_build_candidate_rejects_search_keyword_as_company_name(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://sale.1688.com/factory/example",
            "text": "\u5e7f\u5dde\u7f8e\u5986\u86cb\u5de5\u5382",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u7f8e\u5986\u86cb\u5de5\u5382 \u641c\u7d22 "
                "45%\u54cd\u5e94\u7387 100%\u5c65\u7ea6\u7387 48%\u56de\u5934\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u7f8e\u5986\u86cb\u5de5\u5382",
            raw_item,
            "\u7f8e\u5986\u4e2a\u62a4",
        )

        self.assertIsNone(candidate)

    def test_clean_company_name_removes_ranking_prefix(self):
        self.assertEqual(
            clean_company_name_text(
                "\u6d17\u8138\u6251\u70ed\u5ea6\u699c\u7b2c4\u540d"
                "\u4e3d\u7814\u5316\u5986\u7528\u54c1(\u4e1c\u839e)\u6709\u9650\u516c\u53f8"
            ),
            "\u4e3d\u7814\u5316\u5986\u7528\u54c1(\u4e1c\u839e)\u6709\u9650\u516c\u53f8",
        )

    def test_clean_company_name_rejects_unbalanced_region_parenthesis(self):
        self.assertEqual(clean_company_name_text("广州）化妆品有限公司"), "")
        self.assertEqual(clean_company_name_text("广东）科技有限公司"), "")

    def test_clean_company_name_keeps_balanced_region_parenthesis(self):
        self.assertEqual(
            clean_company_name_text("丽研化妆用品（东莞）有限公司"),
            "丽研化妆用品（东莞）有限公司",
        )

    def test_search_result_rejects_skincare_card_for_nail_keyword(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州美甲工厂",
            "美妆个护",
            "广州某某护肤品有限公司 超级工厂 面膜 护肤品 精华液 98%履约率",
        )

        self.assertFalse(is_relevant)

    def test_search_result_accepts_related_nail_categories_for_nail_keyword(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州美甲工厂",
            "美妆个护",
            "广州某某美甲用品有限公司 超级工厂 甲油胶 穿戴甲 光疗胶 98%履约率",
        )

        self.assertTrue(is_relevant)

    def test_search_result_rejects_skincare_card_for_eyelash_keyword(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州睫毛工厂",
            "美妆个护",
            "广州某某护肤品有限公司 超级工厂 面膜 护肤品 精华液 98%履约率",
        )

        self.assertFalse(is_relevant)

    def test_search_result_accepts_false_eyelash_for_eyelash_keyword(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州睫毛工厂",
            "美妆个护",
            "广州某某睫毛有限公司 超级工厂 假睫毛 接睫毛 睫毛工具 98%履约率",
        )

        self.assertTrue(is_relevant)

    def test_other_industry_accepts_handheld_steamer_related_category(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州手持蒸汽熨烫机工厂",
            "其他",
            "广州市某某电器有限公司 超级工厂 手持挂烫机 蒸汽熨烫机 电熨斗 98%履约率",
        )

        self.assertTrue(is_relevant)

    def test_other_industry_accepts_game_controller_related_category(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州游戏手柄工厂",
            "其他",
            "深圳市某某电子有限公司 超级工厂 无线游戏手柄 蓝牙手柄 电竞手柄 96%履约率",
        )

        self.assertTrue(is_relevant)

    def test_other_industry_accepts_game_keyboard_related_category(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广东游戏键盘",
            "其他",
            "深圳市某某电子有限公司 超级工厂 机械键盘 电竞键盘 键鼠套装 96%履约率",
        )

        self.assertTrue(is_relevant)

    def test_other_industry_accepts_game_mouse_headset_related_category(self):
        collector = Alibaba1688PublicPageCollector()

        mouse_is_relevant = collector.is_search_result_card_relevant(
            "广东游戏鼠标",
            "其他",
            "东莞市某某电子有限公司 超级工厂 电竞鼠标 有线鼠标 键鼠套装 95%履约率",
        )
        headset_is_relevant = collector.is_search_result_card_relevant(
            "广东游戏耳机",
            "其他",
            "广州市某某电子有限公司 超级工厂 电竞耳机 头戴式耳机 耳麦 95%履约率",
        )

        self.assertTrue(mouse_is_relevant)
        self.assertTrue(headset_is_relevant)

    def test_other_industry_rejects_unrelated_product_card(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州游戏手柄工厂",
            "其他",
            "广州市某某电器有限公司 超级工厂 手持挂烫机 蒸汽熨烫机 电熨斗 98%履约率",
        )

        self.assertFalse(is_relevant)

    def test_other_industry_unknown_product_requires_exact_keyword_evidence(self):
        collector = Alibaba1688PublicPageCollector()

        is_relevant = collector.is_search_result_card_relevant(
            "广州宠物烘干箱工厂",
            "其他",
            "广州市某某电子有限公司 超级工厂 无线游戏手柄 蓝牙手柄 98%履约率",
        )

        self.assertFalse(is_relevant)

    def test_build_candidate_extracts_phone_case_categories_from_card_line(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://keduzhang.1688.com/",
            "text": "\u6e05\u8fdc\u7f8e\u5986\u86cb",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u58f3\u961f\u957f\u7535\u5b50\u5546\u52a1\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde \u8d85\u7ea7\u5de5\u5382 "
                "\u624b\u673a\u4fdd\u62a4\u5957 iPhone\u4fdd\u62a4\u5957 "
                "1100m\u00b2 18\u5458\u5de5 \u91d1\u724c\u5236\u9020 "
                "99%\u5c65\u7ea6\u7387 88%\u54cd\u5e94\u7387 52%\u56de\u5934\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u624b\u673a\u58f3\u5de5\u5382",
            raw_item,
            "3C\u6570\u7801",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.product_name, "\u624b\u673a\u4fdd\u62a4\u5957\u3001iPhone\u4fdd\u62a4\u5957")

    def test_build_candidate_keeps_single_3c_card_category_matching_keyword(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://datawire.1688.com/",
            "text": "\u6df1\u5733\u5e02\u5e38\u9752\u7535\u5b50\u7ebf\u6750\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u6df1\u5733\u5e02\u5e38\u9752\u7535\u5b50\u7ebf\u6750\u6709\u9650\u516c\u53f8 "
                "\u6df1\u5733 \u8d85\u7ea7\u5de5\u5382 "
                "\u624b\u673a\u6570\u636e\u7ebf "
                "35%\u54cd\u5e94\u7387 \u672a\u516c\u5f00"
            ),
        }

        candidate = collector.build_candidate(
            "\u6df1\u5733\u624b\u673a\u6570\u636e\u7ebf\u5de5\u5382",
            raw_item,
            "3C\u6570\u7801",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.product_name, "\u624b\u673a\u6570\u636e\u7ebf")

    def test_build_candidate_extracts_company_search_short_category_tokens(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://jingwei.1688.com/",
            "text": "\u4e1c\u839e\u5e02\u6676\u5fae\u7535\u5b50\u79d1\u6280\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u4e1c\u839e\u5e02\u6676\u5fae\u7535\u5b50\u79d1\u6280\u6709\u9650\u516c\u53f8 "
                "\u4e1c\u839e "
                "\u624b\u673a\u914d\u4ef6 \u624b\u673a\u5176\u4ed6\u6570\u7801\u914d\u4ef6 "
                "90%\u54cd\u5e94\u7387 38%\u56de\u5934\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u4e1c\u839e\u5e02\u6676\u5fae\u7535\u5b50\u79d1\u6280\u6709\u9650\u516c\u53f8",
            raw_item,
            "3C\u6570\u7801",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.product_name, "\u624b\u673a\u914d\u4ef6\u3001\u624b\u673a\u5176\u4ed6\u6570\u7801\u914d\u4ef6")

    def test_build_candidate_keeps_visible_company_when_search_city_differs_from_card(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://guangzhou.1688.com/",
            "text": "\u5e7f\u5dde\u5e02\u67d0\u67d0\u670d\u9970\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u5e02\u67d0\u67d0\u670d\u9970\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde \u8d85\u7ea7\u5de5\u5382 "
                "\u5973\u88c5\u6279\u53d1 \u8fde\u8863\u88d9 98%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u4e1c\u839e\u5973\u88c5\u6279\u53d1",
            raw_item,
            "\u670d\u88c5",
            target_city="\u4e1c\u839e\u5e02",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name, "广州市某某服饰有限公司")
        self.assertEqual(candidate.product_name, "女装批发、连衣裙")

    def test_build_candidate_extracts_clothing_categories_from_visible_card_line(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://binlai.1688.com/",
            "text": "\u5e7f\u5dde\u5f6c\u683c\u83b1\u670d\u9970\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u5f6c\u683c\u83b1\u670d\u9970\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde \u8bda7\u5e74 "
                "\u5e7f\u544a\u886bT\u6064 \u5de5\u88c5\u3001\u5236\u670d "
                "\u7537\u5f0fT\u6064 45%\u54cd\u5e94\u7387 "
                "100%\u5c65\u7ea6\u7387 48%\u56de\u5934\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u5e02\u6d77\u73e0\u533a\u6708\u4eae\u670d\u88c5\u5382",
            raw_item,
            "\u670d\u88c5",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.product_name,
            "\u5e7f\u544a\u886bT\u6064\u3001\u5de5\u88c5\u3001\u5236\u670d\u3001\u7537\u5f0fT\u6064",
        )

    def test_extract_card_category_keeps_slash_inside_visible_category(self):
        collector = Alibaba1688PublicPageCollector()

        product = collector.extract_search_card_category_product_name(
            "\u5e7f\u5dde\u5e02\u6d77\u73e0\u533a\u5361\u5974\u5a1c\u5236\u8863\u5382 "
            "\u5e7f\u5dde \u8bda6\u5e74 "
            "\u540a\u5e26\u80cc\u5fc3 \u88f9\u80f8\u3001\u62b9\u80f8 "
            "\u821e\u53f0/\u8868\u6f14\u670d 660m\u00b2 11-50\u4eba "
            "74%\u54cd\u5e94\u7387 98%\u5c65\u7ea6\u7387",
            "\u5e7f\u5dde\u5e02\u6d77\u73e0\u533a\u5361\u5974\u5a1c\u5236\u8863\u5382",
        )

        self.assertEqual(
            product,
            "\u540a\u5e26\u80cc\u5fc3\u3001\u88f9\u80f8\u3001\u62b9\u80f8\u3001\u821e\u53f0/\u8868\u6f14\u670d",
        )

    def test_build_candidate_does_not_fallback_to_anchor_product_when_card_category_missing(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://laxue.1688.com/",
            "text": "\u6e05\u8fdc\u7f8e\u5986\u86cb",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u83b1\u96ea\u5316\u5986\u7528\u54c1\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde 7%\u54cd\u5e94\u7387 \u751f\u4ea7\u5b9e\u529b\u5f3a "
                "3CE\u4f9b\u5e94\u5546"
            ),
        }

        candidate = collector.build_candidate(
            "\u6e05\u8fdc\u7f8e\u5986\u86cb\u5de5\u5382",
            raw_item,
            "\u7f8e\u5986\u4e2a\u62a4",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.product_name, "")

    def test_extract_card_category_keeps_visible_small_categories(self):
        collector = Alibaba1688PublicPageCollector()

        product = collector.extract_search_card_category_product_name(
            "\u4e1c\u839e\u5e02\u864e\u95e8\u4ea6\u535a\u670d\u9970 \u4e1c\u839e "
            "\u8bda2\u5e74 | \u8fde\u8863\u88d9 \u5973\u5f0fT\u6064 "
            "\u5927\u7801\u8fde\u8863\u88d9 \u534a\u8eab\u88d9 | 96%\u54cd\u5e94\u7387 | "
            "100%\u5c65\u7ea6\u7387",
            "\u4e1c\u839e\u5e02\u864e\u95e8\u4ea6\u535a\u670d\u9970",
        )

        self.assertEqual(
            product,
            "\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064\u3001\u5927\u7801\u8fde\u8863\u88d9\u3001\u534a\u8eab\u88d9",
        )

    def test_extract_card_category_keeps_game_peripheral_small_categories(self):
        collector = Alibaba1688PublicPageCollector()

        product = collector.extract_search_card_category_product_name(
            "深圳市锐锋电子有限公司 深圳 超级工厂 "
            "机械键盘 电竞键盘 键鼠套装 96%履约率 88%响应率",
            "深圳市锐锋电子有限公司",
        )

        self.assertEqual(product, "机械键盘、电竞键盘、键鼠套装")

    def test_extract_card_category_keeps_bluetooth_audio_short_categories(self):
        collector = Alibaba1688PublicPageCollector()

        product = collector.extract_search_card_category_product_name(
            "深圳市星河电子有限公司 深圳 超级工厂 "
            "蓝牙音箱 音箱 蓝牙音响 88%响应率 60%回头率",
            "深圳市星河电子有限公司",
        )

        self.assertEqual(product, "蓝牙音箱、音箱、蓝牙音响")

    def test_extract_card_category_keeps_cable_and_charger_short_categories(self):
        collector = Alibaba1688PublicPageCollector()

        product = collector.extract_search_card_category_product_name(
            "东莞市常青电子线材有限公司 东莞 超级工厂 "
            "数据线 充电器 充电线 35%响应率 未公开",
            "东莞市常青电子线材有限公司",
        )

        self.assertEqual(product, "数据线、充电器、充电线")

    def test_build_search_keyword_list_uses_selected_city_prefixes_only(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "3C\u6570\u7801",
            ["\u84dd\u7259\u8033\u673a,\u84dd\u7259\u97f3\u54cd"],
            target_city="\u5e7f\u5dde\u5e02,\u4e1c\u839e\u5e02",
        )

        self.assertEqual(
            keyword_list,
            [
                "\u5e7f\u5dde\u84dd\u7259\u8033\u673a",
                "\u4e1c\u839e\u84dd\u7259\u8033\u673a",
                "\u5e7f\u5dde\u84dd\u7259\u97f3\u54cd",
                "\u4e1c\u839e\u84dd\u7259\u97f3\u54cd",
            ],
        )
        self.assertTrue(all(not keyword.endswith("\u5de5\u5382") for keyword in keyword_list))

    def test_build_search_keyword_list_expands_guangdong_province_to_city_searches(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "3C\u6570\u7801",
            ["\u84dd\u7259\u8033\u673a,\u6570\u636e\u7ebf"],
            target_city="\u5e7f\u4e1c\u7701",
        )

        self.assertEqual(keyword_list[:6], ["广东蓝牙耳机", "蓝牙耳机", "广州蓝牙耳机", "深圳蓝牙耳机", "东莞蓝牙耳机", "佛山蓝牙耳机"])
        self.assertIn("东莞蓝牙耳机", keyword_list)
        self.assertIn("广州数据线", keyword_list)
        self.assertGreater(len(keyword_list), 30)

    def test_build_search_keyword_list_limits_guangdong_province_expansion_for_small_batch(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "3C数码",
            ["蓝牙音响,蓝牙音箱"],
            target_city="广东省",
            collect_limit=10,
        )

        self.assertEqual(
            keyword_list,
            [
                "广东蓝牙音响",
                "蓝牙音响",
                "广州蓝牙音响",
                "深圳蓝牙音响",
                "东莞蓝牙音响",
                "佛山蓝牙音响",
                "广东蓝牙音箱",
                "蓝牙音箱",
                "广州蓝牙音箱",
                "深圳蓝牙音箱",
                "东莞蓝牙音箱",
                "佛山蓝牙音箱",
            ],
        )
        self.assertNotIn("云浮蓝牙音箱", keyword_list)

    def test_build_search_keyword_list_does_not_fallback_to_industry_keywords(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list("\u670d\u88c5", [], target_city="\u5e7f\u4e1c\u7701")

        self.assertEqual(keyword_list, [])

    def test_build_search_keyword_list_uses_selected_guangdong_city(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "\u670d\u88c5",
            ["\u5973\u88c5\u6279\u53d1,\u670d\u88c5OEM"],
            target_city="\u4e1c\u839e\u5e02",
        )

        self.assertEqual(keyword_list, ["\u4e1c\u839e\u5973\u88c5\u6279\u53d1", "\u4e1c\u839e\u670d\u88c5OEM"])
        self.assertNotIn("\u5e7f\u5dde\u5973\u88c5\u6279\u53d1", keyword_list)

    def test_build_search_keyword_list_keeps_nail_beauty_keywords(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "\u7f8e\u5986\u4e2a\u62a4",
            ["\u7f8e\u7532,\u7532\u6cb9\u80f6"],
        )

        self.assertEqual(
            keyword_list[:4],
            [
                "\u5e7f\u4e1c\u7f8e\u7532",
                "\u7f8e\u7532",
                "\u5e7f\u5dde\u7f8e\u7532",
                "\u6df1\u5733\u7f8e\u7532",
            ],
        )
        self.assertIn("\u5e7f\u4e1c\u7532\u6cb9\u80f6", keyword_list)
        self.assertNotIn("\u5e7f\u4e1c\u5316\u5986\u54c1", keyword_list[:10])

    def test_other_industry_search_uses_user_products_and_selected_regions_only(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "其他",
            ["手持蒸汽熨烫机,游戏手柄"],
            target_city="广州,佛山",
        )

        self.assertEqual(
            keyword_list,
            [
                "广州手持蒸汽熨烫机",
                "佛山手持蒸汽熨烫机",
                "广州游戏手柄",
                "佛山游戏手柄",
            ],
        )
        self.assertTrue(all(not keyword.endswith("工厂") for keyword in keyword_list))
        self.assertNotIn("广州服装工厂", keyword_list)

    def test_other_industry_search_uses_selected_guangdong_city_without_factory_suffix(self):
        collector = Alibaba1688PublicPageCollector()

        keyword_list = collector.build_search_keyword_list(
            "其他",
            ["手持蒸汽熨烫机,游戏手柄"],
            target_city="深圳市",
        )

        self.assertEqual(keyword_list, ["深圳手持蒸汽熨烫机", "深圳游戏手柄"])
        self.assertTrue(all(keyword.startswith("深圳") for keyword in keyword_list))
        self.assertTrue(all(not keyword.endswith("工厂") for keyword in keyword_list))

    def test_other_industry_raw_product_search_still_uses_guangdong_province_filter(self):
        collector = Alibaba1688PublicPageCollector()

        search_url = collector.build_search_url_list("手持蒸汽熨烫机", 1)[0]

        self.assertIn(
            f"province={collector.encode_1688_query_value('广东')}",
            search_url,
        )

    def test_build_search_max_page_count_allows_large_batches_to_scan_beyond_three_pages(self):
        collector = Alibaba1688PublicPageCollector()

        self.assertGreaterEqual(collector.build_search_max_page_count(50), 6)

    def test_build_search_max_page_count_allows_small_batches_to_resume_deep_pages(self):
        collector = Alibaba1688PublicPageCollector()

        self.assertEqual(collector.build_search_max_page_count(18), 50)

    def test_build_search_max_page_count_scales_beyond_eight_for_large_batches(self):
        collector = Alibaba1688PublicPageCollector()

        self.assertGreaterEqual(collector.build_search_max_page_count(200), 20)

    def test_build_search_candidate_limit_stays_bounded_when_existing_leads_large(self):
        collector = Alibaba1688PublicPageCollector()
        collector.set_existing_lead_identity_list(
            [
                {
                    "suspected_company_name": f"深圳市已存在电子{index}有限公司",
                    "shop_url": f"https://existing{index}.1688.com/",
                }
                for index in range(1000)
            ]
        )

        self.assertLessEqual(collector.build_search_candidate_limit(50), 80)

    def test_search_candidate_uses_native_pagination_after_initial_search(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        visited_page_number_list = []

        def fake_open_search_result_page(page_obj, keyword, page_number):
            page_obj.current_page_number = page_number
            page_obj.url = f"https://example.test/search?beginPage={page_number}"
            visited_page_number_list.append(page_number)
            return True

        def fake_go_to_search_page(page_obj, page_number):
            page_obj.current_page_number = page_number
            page_obj.url = f"https://example.test/search?beginPage={page_number}"
            visited_page_number_list.append(page_number)
            return True

        def fake_extract_raw_item_list(page_obj):
            return [{"company_name": f"第{page_obj.current_page_number}页公司"}]

        def fake_build_candidate(keyword, raw_item, industry, target_city="广东省"):
            company_name = raw_item["company_name"]
            return AlibabaCandidate(
                source_keyword=keyword,
                company_name=company_name,
                product_name="蓝牙音箱",
                shop_url=f"https://{company_name}.1688.com/",
                profile_url=f"https://{company_name}.1688.com/",
                raw_text=f"{company_name} 东莞 蓝牙音箱",
            )

        with patch.object(
            collector,
            "open_search_result_page",
            create=True,
            side_effect=fake_open_search_result_page,
        ), patch.object(
            collector,
            "go_to_search_page",
            create=True,
            side_effect=fake_go_to_search_page,
        ), patch.object(
            collector,
            "goto_public_page",
            side_effect=AssertionError("后续页不能再通过地址栏直接打开"),
        ), patch.object(collector, "scroll_result_page_to_load"), patch.object(
            collector,
            "extract_raw_item_list",
            side_effect=fake_extract_raw_item_list,
        ), patch.object(collector, "build_candidate", side_effect=fake_build_candidate), patch.object(
            collector,
            "wait_between_page",
        ):
            candidate_list = collector.search_candidate(Mock(), "东莞蓝牙音箱", 3, "3C数码", target_city="东莞市")

        self.assertEqual(visited_page_number_list, [1, 2, 3])
        self.assertEqual(
            [candidate.company_name for candidate in candidate_list],
            ["第1页公司", "第2页公司", "第3页公司"],
        )

    def test_open_search_result_page_reuses_current_keyword_session_when_resuming_next_page(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        page.url = collector.build_search_url_list("深圳蓝牙音箱", 32)[0]

        with patch.object(
            collector,
            "get_current_search_page_number",
            return_value=32,
        ), patch.object(
            collector,
            "goto_public_page",
            side_effect=AssertionError("同一关键词续页时不能重新打开第 1 页"),
        ), patch.object(
            collector,
            "go_to_search_page",
            return_value=True,
        ) as go_to_search_page:
            opened = collector.open_search_result_page(page, "深圳蓝牙音箱", 33)

        self.assertTrue(opened)
        go_to_search_page.assert_called_once_with(page, 33)

    def test_open_search_result_page_waits_until_factory_results_are_ready(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()

        with patch.object(
            collector,
            "get_current_search_page_number",
            return_value=0,
        ), patch.object(
            collector,
            "goto_public_page",
        ), patch.object(
            collector,
            "wait_for_search_result_ready",
            return_value=True,
            create=True,
        ) as wait_for_search_result_ready:
            opened = collector.open_search_result_page(page, "深圳蓝牙音箱", 1)

        self.assertTrue(opened)
        wait_for_search_result_ready.assert_called_once_with(page)

    def test_search_pagination_does_not_advance_past_last_visible_page(self):
        collector = Alibaba1688PublicPageCollector()

        self.assertFalse(
            collector.can_advance_to_search_page(
                current_page_number=38,
                target_page_number=39,
                visible_page_number_list=[1, 34, 35, 36, 37, 38],
            )
        )
        self.assertTrue(
            collector.can_advance_to_search_page(
                current_page_number=32,
                target_page_number=33,
                visible_page_number_list=[1, 30, 31, 32, 33, 34],
            )
        )

    def test_search_candidate_resets_resume_page_after_reaching_last_page(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        page.url = collector.build_search_url_list("深圳蓝牙音箱", 38)[0]

        def fake_go_to_search_page(page_obj, page_number):
            collector.last_search_pagination_reached_end = True
            return False

        with patch.object(
            collector,
            "open_search_result_page",
            return_value=True,
        ), patch.object(
            collector,
            "get_current_search_page_number",
            return_value=38,
        ), patch.object(
            collector,
            "scroll_result_page_to_load",
        ), patch.object(
            collector,
            "extract_raw_item_list",
            return_value=[{"company_name": "深圳市末页音响有限公司"}],
        ), patch.object(
            collector,
            "build_candidate",
            return_value=AlibabaCandidate(
                source_keyword="深圳蓝牙音箱",
                company_name="深圳市末页音响有限公司",
                product_name="蓝牙音箱",
                shop_url="https://last-page.1688.com/",
                profile_url="https://last-page.1688.com/",
                raw_text="深圳市末页音响有限公司 深圳 蓝牙音箱",
            ),
        ), patch.object(
            collector,
            "go_to_search_page",
            side_effect=fake_go_to_search_page,
        ), patch.object(collector, "wait_between_page"):
            candidate_list = collector.search_candidate(
                page,
                "深圳蓝牙音箱",
                20,
                "3C数码",
                target_city="深圳市",
                start_page_number=38,
            )

        self.assertEqual(len(candidate_list), 1)
        self.assertEqual(collector.last_search_candidate_next_page_number, 1)

    def test_search_candidate_falls_back_to_first_page_when_saved_resume_page_is_invalid(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        opened_page_number_list = []

        def fake_open_search_result_page(page_obj, keyword, page_number):
            opened_page_number_list.append(page_number)
            page_obj.url = collector.build_search_url_list(keyword, page_number)[0]
            return page_number == 1

        with patch.object(
            collector,
            "open_search_result_page",
            side_effect=fake_open_search_result_page,
        ), patch.object(
            collector,
            "get_current_search_page_number",
            return_value=1,
        ), patch.object(
            collector,
            "scroll_result_page_to_load",
        ), patch.object(
            collector,
            "extract_raw_item_list",
            return_value=[{"company_name": "深圳市恢复采集有限公司"}],
        ), patch.object(
            collector,
            "build_candidate",
            return_value=AlibabaCandidate(
                source_keyword="深圳蓝牙音箱",
                company_name="深圳市恢复采集有限公司",
                product_name="蓝牙音箱",
                shop_url="https://resume-fallback.1688.com/",
                profile_url="https://resume-fallback.1688.com/",
                raw_text="深圳市恢复采集有限公司 深圳 蓝牙音箱",
            ),
        ):
            candidate_list = collector.search_candidate(
                page,
                "深圳蓝牙音箱",
                1,
                "3C数码",
                target_city="深圳市",
                start_page_number=39,
            )

        self.assertEqual(opened_page_number_list, [39, 1])
        self.assertEqual(len(candidate_list), 1)

    def test_search_candidate_stops_once_candidate_budget_reached(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        visited_page_number_list = []

        def fake_build_search_url_list(keyword, page_number):
            return [f"https://example.test/page-{page_number}"]

        def fake_goto_public_page(page_obj, url):
            page_obj.current_url = url
            visited_page_number_list.append(int(url.rsplit("-", 1)[1]))

        def fake_extract_raw_item_list(page_obj):
            return [{"company_name": f"候选公司{index}"} for index in range(20)]

        def fake_build_candidate(keyword, raw_item, industry, target_city="广东省"):
            company_name = raw_item["company_name"]
            return AlibabaCandidate(
                source_keyword=keyword,
                company_name=company_name,
                product_name="蓝牙音箱",
                shop_url=f"https://{company_name}.1688.com/",
                profile_url=f"https://{company_name}.1688.com/",
                raw_text=f"{company_name} 深圳 蓝牙音箱",
            )

        with patch.object(collector, "build_search_url_list", side_effect=fake_build_search_url_list), patch.object(
            collector,
            "goto_public_page",
            side_effect=fake_goto_public_page,
        ), patch.object(collector, "scroll_result_page_to_load"), patch.object(
            collector,
            "extract_raw_item_list",
            side_effect=fake_extract_raw_item_list,
        ), patch.object(collector, "build_candidate", side_effect=fake_build_candidate), patch.object(
            collector,
            "wait_between_page",
        ):
            candidate_list = collector.search_candidate(Mock(), "蓝牙音箱", 5, "3C数码", target_city="广东省")

        self.assertEqual(visited_page_number_list, [1])
        self.assertEqual(len(candidate_list), 5)

    def test_search_candidate_can_resume_from_saved_page(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        visited_page_number_list = []

        def fake_open_search_result_page(page_obj, keyword, page_number):
            page_obj.current_url = f"https://example.test/page-{page_number}"
            page_obj.url = page_obj.current_url
            visited_page_number_list.append(page_number)
            return True

        def fake_go_to_search_page(page_obj, page_number):
            page_obj.current_url = f"https://example.test/page-{page_number}"
            page_obj.url = page_obj.current_url
            visited_page_number_list.append(page_number)
            return True

        def fake_extract_raw_item_list(page_obj):
            return [{"company_name": f"续采公司{page_obj.current_url.rsplit('-', 1)[1]}"}]

        def fake_build_candidate(keyword, raw_item, industry, target_city="广东省"):
            company_name = raw_item["company_name"]
            return AlibabaCandidate(
                source_keyword=keyword,
                company_name=company_name,
                product_name="蓝牙音箱",
                shop_url=f"https://{company_name}.1688.com/",
                profile_url=f"https://{company_name}.1688.com/",
                raw_text=f"{company_name} 广州 蓝牙音箱",
            )

        with TemporaryDirectory() as tmp_dir, patch.object(
            collector,
            "get_search_progress_file_path",
            return_value=Path(tmp_dir) / "1688_search_progress.json",
        ), patch.object(
            collector,
            "open_search_result_page",
            side_effect=fake_open_search_result_page,
        ), patch.object(
            collector,
            "go_to_search_page",
            side_effect=fake_go_to_search_page,
        ), patch.object(collector, "scroll_result_page_to_load"), patch.object(
            collector,
            "extract_raw_item_list",
            side_effect=fake_extract_raw_item_list,
        ), patch.object(collector, "build_candidate", side_effect=fake_build_candidate), patch.object(
            collector,
            "wait_between_page",
        ):
            collector.save_search_resume_page("广东省", "广州蓝牙音箱", 2)
            start_page = collector.load_search_resume_page("广东省", "广州蓝牙音箱")
            candidate_list = collector.search_candidate(
                Mock(),
                "广州蓝牙音箱",
                1,
                "3C数码",
                target_city="广东省",
                start_page_number=start_page,
            )
            collector.save_search_resume_page(
                "广东省",
                "广州蓝牙音箱",
                collector.last_search_candidate_next_page_number,
            )

            self.assertEqual(visited_page_number_list, [2])
            self.assertEqual(candidate_list[0].company_name, "续采公司2")
            self.assertEqual(collector.load_search_resume_page("广东省", "广州蓝牙音箱"), 3)

    def test_search_candidate_keeps_scanning_after_one_empty_page(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        visited_page_number_list = []

        def fake_open_search_result_page(page_obj, keyword, page_number):
            page_obj.current_url = f"https://example.test/page-{page_number}"
            page_obj.url = page_obj.current_url
            visited_page_number_list.append(page_number)
            return True

        def fake_go_to_search_page(page_obj, page_number):
            page_obj.current_url = f"https://example.test/page-{page_number}"
            page_obj.url = page_obj.current_url
            visited_page_number_list.append(page_number)
            return True

        def fake_extract_raw_item_list(page_obj):
            if page_obj.current_url.endswith("-1"):
                return [{"company_name": "第一页公司"}]
            if page_obj.current_url.endswith("-3"):
                return [{"company_name": "第三页新增公司"}]
            return []

        def fake_build_candidate(keyword, raw_item, industry, target_city="广东省"):
            company_name = raw_item["company_name"]
            return AlibabaCandidate(
                source_keyword=keyword,
                company_name=company_name,
                product_name="蓝牙耳机",
                shop_url=f"https://{company_name}.1688.com/",
                profile_url=f"https://{company_name}.1688.com/",
                raw_text=f"{company_name} 广州 蓝牙耳机",
            )

        with patch.object(
            collector,
            "open_search_result_page",
            side_effect=fake_open_search_result_page,
        ), patch.object(
            collector,
            "go_to_search_page",
            side_effect=fake_go_to_search_page,
        ), patch.object(collector, "scroll_result_page_to_load"), patch.object(
            collector,
            "extract_raw_item_list",
            side_effect=fake_extract_raw_item_list,
        ), patch.object(collector, "build_candidate", side_effect=fake_build_candidate), patch.object(
            collector,
            "wait_between_page",
        ):
            candidate_list = collector.search_candidate(Mock(), "蓝牙耳机", 20, "3C数码", target_city="广州市")

        self.assertIn(3, visited_page_number_list)
        self.assertEqual(collector.last_search_page_count, 6)
        self.assertEqual([candidate.company_name for candidate in candidate_list], ["第一页公司", "第三页新增公司"])

    def test_search_candidate_stops_when_1688_repeats_same_result_page_with_rotating_ad(self):
        collector = Alibaba1688PublicPageCollector()
        page = Mock()
        visited_page_number_list = []

        def fake_open_search_result_page(page_obj, keyword, page_number):
            page_obj.current_url = f"https://example.test/page-{page_number}"
            page_obj.url = page_obj.current_url
            visited_page_number_list.append(page_number)
            return True

        def fake_go_to_search_page(page_obj, page_number):
            page_obj.current_url = f"https://example.test/page-{page_number}"
            page_obj.url = page_obj.current_url
            visited_page_number_list.append(page_number)
            return True

        def fake_extract_raw_item_list(page_obj):
            page_number = page_obj.current_url.rsplit("-", 1)[1]
            return [
                {"company_name": "东莞市固定音响一厂"},
                {"company_name": "东莞市固定音响二厂"},
                {"company_name": "东莞市固定音响三厂"},
                {"company_name": f"轮换推荐{page_number}厂"},
            ]

        def fake_build_candidate(keyword, raw_item, industry, target_city="广东省"):
            company_name = raw_item["company_name"]
            return AlibabaCandidate(
                source_keyword=keyword,
                company_name=company_name,
                product_name="蓝牙音响",
                shop_url=f"https://{company_name}.1688.com/",
                profile_url=f"https://{company_name}.1688.com/",
                raw_text=f"{company_name} 东莞 蓝牙音响",
            )

        with patch.object(
            collector,
            "open_search_result_page",
            side_effect=fake_open_search_result_page,
        ), patch.object(
            collector,
            "go_to_search_page",
            side_effect=fake_go_to_search_page,
        ), patch.object(collector, "scroll_result_page_to_load"), patch.object(
            collector,
            "extract_raw_item_list",
            side_effect=fake_extract_raw_item_list,
        ), patch.object(collector, "build_candidate", side_effect=fake_build_candidate), patch.object(
            collector,
            "wait_between_page",
        ):
            candidate_list = collector.search_candidate(Mock(), "东莞蓝牙音响", 20, "其他", target_city="东莞市")

        self.assertEqual(visited_page_number_list, [1, 2, 3])
        self.assertEqual(collector.last_search_candidate_next_page_number, 1)
        self.assertEqual(collector.last_repeated_search_page_guard_count, 1)
        self.assertEqual(len(candidate_list), 6)

    def test_other_industry_fallback_keeps_guangdong_candidate_only(self):
        collector = Alibaba1688PublicPageCollector()
        guangdong_candidate = AlibabaCandidate(
            source_keyword="广州游戏手柄工厂",
            company_name="深圳市某某电子有限公司",
            product_name="无线游戏手柄、蓝牙手柄",
            shop_url="https://controller.1688.com/",
            profile_url="https://controller.1688.com/",
            raw_text="深圳市某某电子有限公司 深圳 超级工厂 无线游戏手柄 蓝牙手柄",
        )
        non_guangdong_candidate = AlibabaCandidate(
            source_keyword="广州游戏手柄工厂",
            company_name="义乌市某某电子有限公司",
            product_name="无线游戏手柄、蓝牙手柄",
            shop_url="https://yiwu-controller.1688.com/",
            profile_url="https://yiwu-controller.1688.com/",
            raw_text="义乌市某某电子有限公司 浙江义乌 超级工厂 无线游戏手柄 蓝牙手柄",
        )

        guangdong_lead = collector.build_fallback_lead_from_search_candidate(guangdong_candidate, "其他")
        non_guangdong_lead = collector.build_fallback_lead_from_search_candidate(non_guangdong_candidate, "其他")

        self.assertIsNotNone(guangdong_lead)
        self.assertEqual(guangdong_lead.industry, "其他")
        self.assertIsNone(non_guangdong_lead)

    def test_collect_completes_current_keyword_before_next_keyword(self):
        collector = Alibaba1688PublicPageCollector()
        fake_context = Mock()
        fake_context.new_page.return_value = Mock()
        fake_browser_session = BrowserSession(context=fake_context, browser=None)
        fake_playwright_manager = MagicMock()
        searched_keyword_list = []

        def fake_search_candidate(page, keyword, search_limit, industry, target_city="广东省", start_page_number=1):
            searched_keyword_list.append((keyword, search_limit))
            return [
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name=f"\u5e7f\u5dde\u5e02{keyword}{index}\u6709\u9650\u516c\u53f8",
                    product_name="\u8fde\u8863\u88d9",
                    shop_url=f"https://example{len(searched_keyword_list)}-{index}.1688.com/",
                    profile_url=f"https://example{len(searched_keyword_list)}-{index}.1688.com/",
                    raw_text=f"{keyword} \u5e7f\u5dde \u8fde\u8863\u88d9",
                )
                for index in range(search_limit)
            ]

        def fake_candidate_to_lead(page, candidate, industry, detail_fallback_count):
            return CollectedLeadDTO(
                source_type="alibaba_1688",
                source_keyword=candidate.source_keyword,
                industry=industry,
                suspected_company_name=candidate.company_name,
                product_name=candidate.product_name,
                shop_url=candidate.shop_url,
                profile_url=candidate.profile_url,
                region_text=candidate.raw_text,
            )

        with patch("app.service.collector_service.sync_playwright", return_value=fake_playwright_manager), patch.object(
            collector,
            "create_browser_session",
            return_value=fake_browser_session,
        ), patch.object(collector, "search_candidate", side_effect=fake_search_candidate), patch.object(
            collector,
            "collect_search_candidate_to_lead",
            side_effect=fake_candidate_to_lead,
        ), patch.object(collector, "wait_after_collected_lead"):
            lead_list = collector.collect(
                "3C\u6570\u7801",
                ["\u84dd\u7259\u8033\u673a,\u84dd\u7259\u97f3\u54cd"],
                3,
                target_city="\u5e7f\u5dde\u5e02,\u4e1c\u839e\u5e02",
            )

        self.assertEqual(len(lead_list), 3)
        self.assertEqual(
            [keyword for keyword, _ in searched_keyword_list],
            ["\u5e7f\u5dde\u84dd\u7259\u8033\u673a"],
        )
        self.assertTrue(all("\u84dd\u7259\u8033\u673a" in lead.source_keyword for lead in lead_list))

    def test_collect_continues_same_keyword_when_first_page_is_existing_duplicate(self):
        collector = Alibaba1688PublicPageCollector()
        collector.set_existing_lead_identity_list([{"suspected_company_name": "广州市已存在电子有限公司"}])
        fake_context = Mock()
        fake_context.new_page.return_value = Mock()
        fake_browser_session = BrowserSession(context=fake_context, browser=None)
        fake_playwright_manager = MagicMock()
        searched_start_page_list = []

        def fake_search_candidate(page, keyword, search_limit, industry, target_city="广东省", start_page_number=1):
            searched_start_page_list.append(start_page_number)
            if start_page_number == 1:
                collector.last_search_candidate_next_page_number = 2
                return [
                    AlibabaCandidate(
                        source_keyword=keyword,
                        company_name="广州市已存在电子有限公司",
                        product_name="蓝牙耳机",
                        shop_url="https://existing.1688.com/",
                        profile_url="https://existing.1688.com/",
                        raw_text="广州市已存在电子有限公司 广州 蓝牙耳机",
                    )
                ]
            collector.last_search_candidate_next_page_number = 3
            return [
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name=f"广州市新增电子{index}有限公司",
                    product_name="蓝牙耳机",
                    shop_url=f"https://new{index}.1688.com/",
                    profile_url=f"https://new{index}.1688.com/",
                    raw_text=f"广州市新增电子{index}有限公司 广州 蓝牙耳机",
                )
                for index in range(2)
            ]

        def fake_candidate_to_lead(page, candidate, industry, detail_fallback_count):
            return CollectedLeadDTO(
                source_type="alibaba_1688",
                source_keyword=candidate.source_keyword,
                industry=industry,
                suspected_company_name=candidate.company_name,
                product_name=candidate.product_name,
                shop_url=candidate.shop_url,
                profile_url=candidate.profile_url,
                region_text=candidate.raw_text,
            )

        with TemporaryDirectory() as tmp_dir, patch.object(
            collector,
            "get_search_progress_file_path",
            return_value=Path(tmp_dir) / "1688_search_progress.json",
        ), patch("app.service.collector_service.sync_playwright", return_value=fake_playwright_manager), patch.object(
            collector,
            "create_browser_session",
            return_value=fake_browser_session,
        ), patch.object(collector, "search_candidate", side_effect=fake_search_candidate), patch.object(
            collector,
            "collect_search_candidate_to_lead",
            side_effect=fake_candidate_to_lead,
        ), patch.object(collector, "wait_after_collected_lead"), patch.object(
            collector,
            "wait_between_page",
        ) as wait_between_page:
            lead_list = collector.collect(
                "3C数码",
                ["蓝牙耳机"],
                2,
                target_city="广州市",
            )

        self.assertEqual(searched_start_page_list, [1, 2])
        wait_between_page.assert_called_once_with()
        self.assertEqual(len(lead_list), 2)
        self.assertEqual([lead.suspected_company_name for lead in lead_list], ["广州市新增电子0有限公司", "广州市新增电子1有限公司"])

    def test_collect_ignores_already_closed_browser_during_cleanup(self):
        collector = Alibaba1688PublicPageCollector()
        fake_context = Mock()
        fake_context.new_page.return_value = Mock()
        fake_context.close.side_effect = PlaywrightTimeoutError("Target page, context or browser has been closed")
        fake_browser_session = BrowserSession(context=fake_context, browser=None)
        fake_playwright_manager = MagicMock()

        with patch("app.service.collector_service.sync_playwright", return_value=fake_playwright_manager), patch.object(
            collector,
            "create_browser_session",
            return_value=fake_browser_session,
        ), patch.object(collector, "search_candidate", return_value=[]):
            lead_list = collector.collect("3C数码", ["蓝牙音响"], 1, target_city="东莞市")

        self.assertEqual(lead_list, [])
        fake_context.close.assert_called_once_with()

    def test_collect_records_partial_diagnostic_when_existing_leads_exhaust_results(self):
        collector = Alibaba1688PublicPageCollector()
        collector.set_existing_lead_identity_list([{"suspected_company_name": "广州市已存在电子有限公司"}])
        fake_context = Mock()
        fake_context.new_page.return_value = Mock()
        fake_browser_session = BrowserSession(context=fake_context, browser=None)
        fake_playwright_manager = MagicMock()

        def fake_search_candidate(page, keyword, search_limit, industry, target_city="广东省", start_page_number=1):
            if keyword == "广州蓝牙耳机":
                return [
                    AlibabaCandidate(
                        source_keyword=keyword,
                        company_name="广州市已存在电子有限公司",
                        product_name="蓝牙耳机",
                        shop_url="https://existing.1688.com/",
                        profile_url="https://existing.1688.com/",
                        raw_text="广州市已存在电子有限公司 广州 蓝牙耳机",
                    )
                ]
            return [
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name="广州市新增电子有限公司",
                    product_name="蓝牙耳机",
                    shop_url="https://new.1688.com/",
                    profile_url="https://new.1688.com/",
                    raw_text="广州市新增电子有限公司 广州 蓝牙耳机",
                )
            ]

        def fake_candidate_to_lead(page, candidate, industry, detail_fallback_count):
            return CollectedLeadDTO(
                source_type="alibaba_1688",
                source_keyword=candidate.source_keyword,
                industry=industry,
                suspected_company_name=candidate.company_name,
                product_name=candidate.product_name,
                shop_url=candidate.shop_url,
                profile_url=candidate.profile_url,
                region_text=candidate.raw_text,
            )

        with patch("app.service.collector_service.sync_playwright", return_value=fake_playwright_manager), patch.object(
            collector,
            "create_browser_session",
            return_value=fake_browser_session,
        ), patch.object(collector, "search_candidate", side_effect=fake_search_candidate), patch.object(
            collector,
            "collect_search_candidate_to_lead",
            side_effect=fake_candidate_to_lead,
        ), patch.object(collector, "wait_after_collected_lead"):
            lead_list = collector.collect(
                "3C数码",
                ["蓝牙耳机,蓝牙音箱"],
                2,
                target_city="广州市",
            )

        self.assertEqual(len(lead_list), 1)
        self.assertEqual(collector.last_existing_skip_count, 1)
        self.assertIn("只采集到 1/2", collector.last_collect_diagnostic)
        self.assertIn("已存在/重复线索 1", collector.last_collect_diagnostic)

    def test_collect_records_existing_duplicate_diagnostic_when_no_new_leads_saved(self):
        collector = Alibaba1688PublicPageCollector()
        collector.set_existing_lead_identity_list([{"suspected_company_name": "深圳市已存在电子有限公司"}])
        fake_context = Mock()
        fake_context.new_page.return_value = Mock()
        fake_browser_session = BrowserSession(context=fake_context, browser=None)
        fake_playwright_manager = MagicMock()

        def fake_search_candidate(page, keyword, search_limit, industry, target_city="广东省", start_page_number=1):
            return [
                AlibabaCandidate(
                    source_keyword=keyword,
                    company_name="深圳市已存在电子有限公司",
                    product_name="蓝牙音箱",
                    shop_url="https://existing-speaker.1688.com/",
                    profile_url="https://existing-speaker.1688.com/",
                    raw_text="深圳市已存在电子有限公司 深圳 蓝牙音箱",
                )
            ]

        def fake_candidate_to_lead(page, candidate, industry, detail_fallback_count):
            return CollectedLeadDTO(
                source_type="alibaba_1688",
                source_keyword=candidate.source_keyword,
                industry=industry,
                suspected_company_name=candidate.company_name,
                product_name=candidate.product_name,
                shop_url=candidate.shop_url,
                profile_url=candidate.profile_url,
                region_text=candidate.raw_text,
            )

        with patch("app.service.collector_service.sync_playwright", return_value=fake_playwright_manager), patch.object(
            collector,
            "create_browser_session",
            return_value=fake_browser_session,
        ), patch.object(collector, "search_candidate", side_effect=fake_search_candidate), patch.object(
            collector,
            "collect_search_candidate_to_lead",
            side_effect=fake_candidate_to_lead,
        ), patch.object(collector, "wait_after_collected_lead"):
            lead_list = collector.collect(
                "3C数码",
                ["蓝牙音箱"],
                1,
                target_city="深圳市",
        )

        self.assertEqual(lead_list, [])
        self.assertEqual(collector.last_existing_skip_count, 1)
        self.assertIn("已存在/重复线索 1", collector.last_collect_diagnostic)
        self.assertNotIn("没有进入详情页", collector.last_collect_diagnostic)

    def test_fallback_lead_accepts_1688_guangdong_filtered_search_page_candidate(self):
        collector = Alibaba1688PublicPageCollector()
        candidate = AlibabaCandidate(
            source_keyword="蓝牙音箱",
            company_name="星河声学科技有限公司",
            product_name="蓝牙音箱",
            shop_url="https://speaker.1688.com/",
            profile_url="https://speaker.1688.com/",
            search_url=collector.build_search_url_list("蓝牙音箱", 1)[0],
            raw_text="星河声学科技有限公司 超级工厂 蓝牙音箱 65%回头率",
        )

        lead = collector.build_fallback_lead_from_search_candidate(candidate, "3C数码")

        self.assertIsNotNone(lead)
        self.assertEqual(lead.suspected_company_name, "星河声学科技有限公司")
        self.assertIn("1688广东筛选页", lead.region_text)

    def test_target_city_card_text_accepts_any_selected_city(self):
        collector = Alibaba1688PublicPageCollector()

        self.assertTrue(collector.is_target_city_card_text("广州,东莞", "东莞市某某电子有限公司 东莞 超级工厂"))
        self.assertFalse(collector.is_target_city_card_text("广州,东莞", "深圳市某某电子有限公司 深圳 超级工厂"))

    def test_collect_candidate_to_lead_does_not_open_detail_by_default(self):
        collector = Alibaba1688PublicPageCollector()
        candidate = AlibabaCandidate(
            source_keyword="\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            company_name="\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            product_name="\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064\u3001\u5927\u7801\u8fde\u8863\u88d9",
            shop_url="https://example.1688.com/",
            profile_url="https://example.1688.com/",
            raw_text=(
                "\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde \u8d85\u7ea7\u5de5\u5382 "
                "\u8fde\u8863\u88d9 \u5973\u5f0fT\u6064 \u5927\u7801\u8fde\u8863\u88d9"
            ),
        )
        collector.enrich_candidate = Mock(side_effect=AssertionError("detail should not be opened"))

        lead = collector.collect_search_candidate_to_lead(Mock(), candidate, "\u670d\u88c5", 0)

        self.assertEqual(lead.suspected_company_name, "\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8")
        self.assertEqual(lead.product_name, "\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064\u3001\u5927\u7801\u8fde\u8863\u88d9")

    def test_click_candidate_company_entry_does_not_click_twice_when_no_popup_opens(self):
        collector = Alibaba1688PublicPageCollector()
        candidate = AlibabaCandidate(
            source_keyword="\u5e7f\u5dde\u84dd\u7259\u97f3\u7bb1",
            company_name="\u5e7f\u5dde\u5e02\u6d4b\u8bd5\u7535\u5b50\u6709\u9650\u516c\u53f8",
            product_name="\u84dd\u7259\u97f3\u7bb1",
            shop_url="https://example.1688.com/",
            profile_url="https://example.1688.com/",
            raw_text="\u5e7f\u5dde\u5e02\u6d4b\u8bd5\u7535\u5b50\u6709\u9650\u516c\u53f8 \u5e7f\u5dde \u84dd\u7259\u97f3\u7bb1",
        )
        locator = MagicMock()
        locator.count.return_value = 1
        locator.first = locator
        page = MagicMock()
        page.locator.return_value = locator
        page.get_by_text.return_value = locator
        popup_context = MagicMock()
        popup_context.__enter__.return_value = MagicMock()
        popup_context.__exit__.side_effect = PlaywrightTimeoutError("no popup")
        page.expect_popup.return_value = popup_context

        with patch.object(collector, "assert_public_page_allowed", return_value=False):
            detail_page = collector.click_candidate_company_entry(page, candidate)

        self.assertIs(detail_page, page)
        locator.click.assert_called_once_with(timeout=4000)

    def test_collect_candidate_to_lead_keeps_company_when_card_product_missing(self):
        collector = Alibaba1688PublicPageCollector()
        candidate = AlibabaCandidate(
            source_keyword="广东游戏键盘",
            company_name="深圳市锐锋电子有限公司",
            product_name="",
            shop_url="https://keyboard.1688.com/",
            profile_url="https://keyboard.1688.com/",
            raw_text=(
                "深圳市锐锋电子有限公司 深圳 超级工厂 "
                "生产实力强 96%履约率 88%响应率"
            ),
        )

        with patch.object(collector, "should_use_detail_fallback", return_value=False):
            lead = collector.collect_search_candidate_to_lead(Mock(), candidate, "其他", 0)

        self.assertIsNotNone(lead)
        self.assertEqual(lead.suspected_company_name, "深圳市锐锋电子有限公司")
        self.assertEqual(lead.product_name, "")

    def test_build_candidate_keeps_1688_detail_link_as_profile_url(self):
        collector = Alibaba1688PublicPageCollector()
        raw_item = {
            "href": "https://detail.1688.com/offer/123456.html?spm=a26352",
            "text": "\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            "title": "",
            "parentText": (
                "\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8 "
                "\u5e7f\u5dde \u8d85\u7ea7\u5de5\u5382 "
                "\u8fde\u8863\u88d9 \u5973\u5f0fT\u6064 \u5927\u7801\u8fde\u8863\u88d9 "
                "96%\u54cd\u5e94\u7387 100%\u5c65\u7ea6\u7387"
            ),
        }

        candidate = collector.build_candidate(
            "\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            raw_item,
            "\u670d\u88c5",
        )
        lead = collector.build_lead_from_candidate_text(candidate, "\u670d\u88c5")

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.shop_url, "")
        self.assertEqual(candidate.profile_url, "https://detail.1688.com/offer/123456.html?spm=a26352")
        self.assertEqual(lead.profile_url, "https://detail.1688.com/offer/123456.html?spm=a26352")

    def test_build_lead_uses_search_url_when_candidate_has_no_direct_link(self):
        collector = Alibaba1688PublicPageCollector()
        candidate = AlibabaCandidate(
            source_keyword="\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            company_name="\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            product_name="\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064",
            shop_url="",
            profile_url="",
            raw_text="\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8 \u5e7f\u5dde \u8fde\u8863\u88d9",
            search_url="https://s.1688.com/company/pc/factory_search.htm?keywords=test",
        )

        lead = collector.build_lead_from_candidate_text(candidate, "\u670d\u88c5")

        self.assertEqual(lead.profile_url, "https://s.1688.com/company/pc/factory_search.htm?keywords=test")

    def test_tianyancha_enrichment_does_not_overwrite_1688_product(self):
        collector = Alibaba1688TianyanchaCollector()
        target = CollectedLeadDTO(
            source_type="alibaba_1688",
            source_keyword="\u5e7f\u5dde\u670d\u88c5\u5de5\u5382",
            industry="\u670d\u88c5",
            suspected_company_name="\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            product_name="\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064\u3001\u5927\u7801\u8fde\u8863\u88d9",
        )
        source = CollectedLeadDTO(
            source_type="tianyancha_public_web",
            source_keyword="\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            industry="\u670d\u88c5",
            suspected_company_name="\u5e7f\u5dde\u5e02\u7389\u9e4f\u670d\u88c5\u6709\u9650\u516c\u53f8",
            product_name="\u670d\u88c5\u4ea7\u54c1",
            phone="13800138000",
        )

        collector.merge_enrichment(target, source)

        self.assertEqual(target.product_name, "\u8fde\u8863\u88d9\u3001\u5973\u5f0fT\u6064\u3001\u5927\u7801\u8fde\u8863\u88d9")

    def test_build_jittered_milliseconds_applies_ratio_and_minimum(self):
        with patch("app.service.collector_service.random.uniform", return_value=250):
            milliseconds = build_jittered_milliseconds(1000, jitter_ratio=0.5, min_milliseconds=700)

        self.assertEqual(milliseconds, 1250)

    def test_build_jittered_milliseconds_respects_minimum(self):
        with patch("app.service.collector_service.random.uniform", return_value=-500):
            milliseconds = build_jittered_milliseconds(1000, jitter_ratio=0.5, min_milliseconds=700)

        self.assertEqual(milliseconds, 700)

    def test_manual_recovery_opens_login_page_for_qr_scan(self):
        collector = Alibaba1688PublicPageCollector()
        collector.emit_task_event = Mock()
        fake_context = Mock()
        fake_page = Mock()
        fake_page.context = fake_context

        with patch.object(collector, "is_feedback_page", return_value=False), patch.object(
            collector,
            "get_blocked_reason",
            return_value="",
        ):
            collector.wait_for_manual_recovery(fake_page, "1688公开页面出现验证要求")

        fake_context.clear_cookies.assert_called_once()
        fake_page.goto.assert_called_once_with(
            ALIBABA_1688_LOGIN_URL,
            wait_until="domcontentloaded",
            timeout=collector.config.alibaba_1688_page_timeout_ms,
        )
        fake_page.bring_to_front.assert_called_once()
        self.assertIn("扫码", collector.emit_task_event.call_args_list[0].args[2])

    def test_reveal_phone_checks_risk_control_before_clicking(self):
        collector = Alibaba1688PublicPageCollector()
        fake_page = Mock()

        with patch.object(collector, "assert_public_page_allowed", return_value=True) as assert_allowed, patch.object(
            collector,
            "click_visible_text_button",
            return_value=True,
        ) as click_button:
            result = collector.reveal_public_phone(fake_page)

        self.assertEqual(result, "")
        assert_allowed.assert_called_once_with(fake_page)
        click_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
