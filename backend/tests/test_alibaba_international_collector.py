import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.core.config import BACKEND_DIR, get_config
from app.model.schema import CollectedLeadDTO
from app.service import alibaba_international_collector as collector_module
from app.service.alibaba_international_collector import (
    AlibabaInternationalSupplierCollector,
)


class AlibabaInternationalCollectorTest(unittest.TestCase):
    def setUp(self):
        self.collector = AlibabaInternationalSupplierCollector()

    def build_raw_item(
        self,
        *,
        company_name_en="Shenzhen Cico Technology Co., Ltd.",
        location_text="Guangdong, China",
        main_products=None,
        badges=None,
        profile_url="https://example.en.alibaba.com/",
        use_brief_keys=False,
    ):
        product_list = (
            main_products
            if main_products is not None
            else [
                "Game Controllers",
                "Gamepads",
                "Mobile Gaming Accessories",
            ]
        )
        badge_list = (
            badges
            if badges is not None
            else [
                "Verified Supplier",
                "Custom Manufacturer",
                "Trade Assurance",
                "5 Yrs",
                "Response Time",
            ]
        )
        if use_brief_keys:
            return {
                "companyName": company_name_en,
                "locationText": location_text,
                "mainProducts": product_list,
                "badgeTextList": badge_list,
                "profileUrl": profile_url,
            }
        return {
            "company_name_en": company_name_en,
            "location_text": location_text,
            "main_products": product_list,
            "badges": badge_list,
            "profile_url": profile_url,
        }

    def test_build_candidate_parses_valid_guangdong_supplier_card(self):
        candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(),
            "3C数码",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.source_keyword, "game controller factory")
        self.assertEqual(candidate.company_name_en, "Shenzhen Cico Technology Co., Ltd.")
        self.assertEqual(
            candidate.product_name,
            "Game Controllers; Gamepads; Mobile Gaming Accessories",
        )
        self.assertEqual(
            candidate.shop_level,
            "Verified Supplier; Custom Manufacturer",
        )
        self.assertEqual(candidate.location_text, "Guangdong, China")
        self.assertEqual(candidate.profile_url, "https://example.en.alibaba.com/")

    def test_build_search_text_prefixes_selected_guangdong_city(self):
        self.assertEqual(
            self.collector.build_search_text("game controller", "广州市"),
            "Guangzhou game controller",
        )
        self.assertEqual(
            self.collector.build_search_text("game controller", "广东省"),
            "Guangdong game controller",
        )

    def test_build_search_plan_uses_selected_city_variants_before_original_keyword_fallback(self):
        self.assertEqual(
            self.collector.build_search_plan(["game controller", "usb cable"], "广州市,东莞市"),
            [
                ("game controller", "广州市", "Guangzhou game controller"),
                ("game controller", "东莞市", "Dongguan game controller"),
                ("game controller", "广东省", "game controller"),
                ("usb cable", "广州市", "Guangzhou usb cable"),
                ("usb cable", "东莞市", "Dongguan usb cable"),
                ("usb cable", "广东省", "usb cable"),
            ],
        )

    def test_build_search_plan_searches_selected_city_before_english_keyword_fallback(self):
        self.assertEqual(
            self.collector.build_search_plan(["silver jewelry"], "东莞市"),
            [
                ("silver jewelry", "东莞市", "Dongguan silver jewelry"),
                ("silver jewelry", "广东省", "silver jewelry"),
            ],
        )

    def test_target_city_filter_accepts_only_selected_city(self):
        self.assertTrue(
            self.collector.is_target_location("Guangzhou, Guangdong, China", "广州市")
        )
        self.assertFalse(
            self.collector.is_target_location("Shenzhen, Guangdong, China", "广州市")
        )
        self.assertTrue(
            self.collector.is_target_location("Shenzhen, Guangdong, China", "广东省")
        )

    def test_target_city_filter_accepts_any_selected_city(self):
        self.assertTrue(
            self.collector.is_target_location("Dongguan, Guangdong, China", "广州市,东莞市")
        )
        self.assertFalse(
            self.collector.is_target_location("Shenzhen, Guangdong, China", "广州市,东莞市")
        )

    def test_build_candidate_keeps_supplier_outside_selected_city_when_search_result_contains_company(self):
        candidate = self.collector.build_candidate(
            "game controller",
            self.build_raw_item(location_text="Shenzhen, Guangdong, China"),
            "3C数码",
            target_city="广州市",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name_en, "Shenzhen Cico Technology Co., Ltd.")
        self.assertEqual(candidate.location_text, "Shenzhen, Guangdong, China")

    def test_build_candidate_supports_exact_brief_payload_keys(self):
        candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(use_brief_keys=True),
            "3C数码",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company_name_en, "Shenzhen Cico Technology Co., Ltd.")
        self.assertEqual(candidate.location_text, "Guangdong, China")
        self.assertEqual(
            candidate.product_name,
            "Game Controllers; Gamepads; Mobile Gaming Accessories",
        )
        self.assertEqual(
            candidate.shop_level,
            "Verified Supplier; Custom Manufacturer",
        )
        self.assertEqual(candidate.profile_url, "https://example.en.alibaba.com/")

    def test_build_candidate_preserves_visible_text_for_stored_fields(self):
        candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                company_name_en="  ShenZhen  Cico TECHNOLOGY Co., Ltd.  ",
                location_text="  ShenZhen  , GuangDong  ",
                main_products=[
                    "  Pro  Game Controllers  ",
                    "Mobile   Gaming Accessories",
                ],
                badges=[
                    "  verified supplier  ",
                    "Custom   Manufacturer",
                    "Trade Assurance",
                ],
                profile_url="  HTTPS://Example.EN.Alibaba.com/Store Path/  ",
                use_brief_keys=True,
            ),
            "3C数码",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.company_name_en,
            "ShenZhen  Cico TECHNOLOGY Co., Ltd.",
        )
        self.assertEqual(
            candidate.product_name,
            "Pro  Game Controllers; Mobile   Gaming Accessories",
        )
        self.assertEqual(candidate.location_text, "ShenZhen  , GuangDong")
        self.assertEqual(candidate.profile_url, "HTTPS://Example.EN.Alibaba.com/Store Path/")
        self.assertEqual(
            candidate.shop_level,
            "verified supplier; Custom   Manufacturer",
        )

    def test_build_candidate_keeps_non_guangdong_and_generic_china_locations_for_later_verification(self):
        for location_text in ("Zhejiang, China", "China"):
            with self.subTest(location_text=location_text):
                candidate = self.collector.build_candidate(
                    "game controller factory",
                    self.build_raw_item(
                        company_name_en=f"{location_text.replace(',', '').replace(' ', '')} Supplier Co., Ltd.",
                        location_text=location_text,
                        profile_url=f"https://{location_text.replace(',', '').replace(' ', '').lower()}.en.alibaba.com/",
                    ),
                    "3C数码",
                )

                self.assertIsNotNone(candidate)
                self.assertEqual(candidate.location_text, location_text)

    def test_build_candidate_rejects_missing_company_name(self):
        candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(company_name_en="   ", use_brief_keys=True),
            "3C数码",
        )

        self.assertIsNone(candidate)

    def test_build_candidate_rejects_non_english_company_name(self):
        candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(company_name_en="深圳市西科科技有限公司", use_brief_keys=True),
            "3C数码",
        )

        self.assertIsNone(candidate)

    def test_build_candidate_keeps_missing_or_unrelated_products_without_blocking_company_collection(self):
        missing_products_candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                company_name_en="Guangzhou Missing Products Co., Ltd.",
                main_products=[],
                profile_url="https://missing-products.en.alibaba.com/",
            ),
            "3C数码",
        )
        unrelated_products_candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                company_name_en="Guangzhou Unrelated Products Co., Ltd.",
                main_products=["USB Cables", "Phone Chargers"],
                profile_url="https://different.en.alibaba.com/",
            ),
            "3C数码",
        )

        self.assertIsNotNone(missing_products_candidate)
        self.assertEqual(missing_products_candidate.product_name, "")
        self.assertIsNotNone(unrelated_products_candidate)
        self.assertEqual(unrelated_products_candidate.product_name, "USB Cables; Phone Chargers")

    def test_build_candidate_allows_empty_badges(self):
        candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                badges=[],
                profile_url="https://empty-badges.en.alibaba.com/",
            ),
            "3C数码",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.shop_level, "")

    def test_build_candidate_dedupes_normalized_company_names(self):
        first_candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                company_name_en="Shenzhen Cico Technology Co., Ltd.",
                profile_url="https://company-name-one.en.alibaba.com/",
            ),
            "3C数码",
        )
        duplicate_candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                company_name_en="Shenzhen  Cico Technology Co Ltd",
                profile_url="https://company-name-two.en.alibaba.com/",
            ),
            "3C数码",
        )

        self.assertIsNotNone(first_candidate)
        self.assertIsNone(duplicate_candidate)

    def test_build_candidate_dedupes_normalized_profile_urls(self):
        first_candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                profile_url="https://profile-dup.en.alibaba.com",
            ),
            "3C数码",
        )
        duplicate_candidate = self.collector.build_candidate(
            "game controller factory",
            self.build_raw_item(
                company_name_en="Shenzhen Cico Technology Group Co., Ltd.",
                profile_url="https://profile-dup.en.alibaba.com/",
            ),
            "3C数码",
        )

        self.assertIsNotNone(first_candidate)
        self.assertIsNone(duplicate_candidate)

    def test_build_candidate_skips_supplier_already_stored_in_lead_library(self):
        self.collector.set_existing_lead_identity_list(
            [
                {
                    "company_name": "Shenzhen Cico Technology Co., Ltd.",
                    "suspected_company_name": "",
                    "profile_url": "https://example.en.alibaba.com/company_profile.html",
                    "shop_url": "",
                }
            ]
        )

        candidate = self.collector.build_candidate(
            "game controller",
            self.build_raw_item(
                profile_url="https://example.en.alibaba.com/company_profile.html?from=search",
            ),
            "3C数码",
        )

        self.assertIsNone(candidate)
        self.assertEqual(self.collector.last_existing_skip_count, 1)

    def test_is_guangdong_location_only_accepts_explicit_guangdong_tokens(self):
        self.assertTrue(self.collector.is_guangdong_location("Guangdong, China"))
        self.assertTrue(self.collector.is_guangdong_location("Shenzhen, China"))
        self.assertFalse(self.collector.is_guangdong_location("China"))
        self.assertFalse(self.collector.is_guangdong_location("Zhejiang, China"))

    def test_build_search_url_targets_supplier_results_with_unchanged_keyword(self):
        search_url = self.collector.build_search_url("game controller", 2)

        parsed_url = urlparse(search_url)
        query = parse_qs(parsed_url.query)
        self.assertEqual(parsed_url.netloc, "www.alibaba.com")
        self.assertIn("/trade/search", parsed_url.path)
        self.assertEqual(query.get("IndexArea"), ["company_en"])
        self.assertEqual(query.get("SearchText"), ["game controller"])
        self.assertEqual(query.get("page"), ["2"])
        self.assertIn("SearchText=game%20controller", search_url)
        self.assertNotIn("factory", search_url.lower())
        self.assertNotIn("manufacturer", search_url.lower())

    def test_build_search_url_preserves_factory_and_manufacturer_when_user_supplies_them(self):
        search_url = self.collector.build_search_url("game controller factory manufacturer", 1)

        query = parse_qs(urlparse(search_url).query)
        search_text = query.get("SearchText", [""])[0]
        self.assertEqual(search_text, "game controller factory manufacturer")
        self.assertEqual(search_text.count("factory"), 1)
        self.assertEqual(search_text.count("manufacturer"), 1)
        self.assertIn("SearchText=game%20controller%20factory%20manufacturer", search_url)

    def test_build_lead_converts_supplier_card_without_losing_raw_fields(self):
        lead = self.collector.build_lead(
            "game controller",
            "3C鏁扮爜",
            self.build_raw_item(use_brief_keys=True),
        )

        self.assertIsInstance(lead, CollectedLeadDTO)
        self.assertEqual(lead.source_type, "alibaba_international")
        self.assertEqual(lead.source_keyword, "game controller")
        self.assertEqual(lead.industry, "3C鏁扮爜")
        self.assertEqual(lead.suspected_company_name, "Shenzhen Cico Technology Co., Ltd.")
        self.assertEqual(lead.company_name_en, "Shenzhen Cico Technology Co., Ltd.")
        self.assertEqual(
            lead.product_name,
            "Game Controllers; Gamepads; Mobile Gaming Accessories",
        )
        self.assertEqual(lead.shop_level, "Verified Supplier; Custom Manufacturer")
        self.assertEqual(lead.region_text, "Guangdong, China")
        self.assertEqual(lead.shop_url, "https://example.en.alibaba.com/")
        self.assertEqual(lead.profile_url, "https://example.en.alibaba.com/")

    def test_config_defaults_use_dedicated_alibaba_international_profile(self):
        get_config.cache_clear()
        config = get_config()

        self.assertFalse(config.alibaba_international_headless)
        self.assertEqual(config.alibaba_international_browser_channel, "msedge")
        self.assertEqual(config.alibaba_international_page_timeout_ms, 25000)
        self.assertEqual(config.alibaba_international_request_interval_seconds, 5.0)
        self.assertTrue(config.alibaba_international_manual_verify_enabled)
        self.assertEqual(
            config.alibaba_international_user_data_dir,
            BACKEND_DIR / "data" / "browser-profile" / "alibaba-international",
        )
        self.assertNotEqual(
            config.alibaba_international_user_data_dir,
            config.alibaba_1688_user_data_dir,
        )
        self.assertTrue(config.alibaba_international_user_data_dir.exists())

    def test_public_result_page_header_sign_in_and_login_words_are_allowed(self):
        class FakeLocator:
            def inner_text(self, timeout):
                return (
                    "Sign in | Login | Join Free\n"
                    "Shenzhen Cico Technology Co., Ltd.\n"
                    "Guangdong, China\n"
                    "Main products: Game Controllers"
                )

        class FakePage:
            url = "https://www.alibaba.com/trade/search?IndexArea=company_en&SearchText=game%20controller"

            def title(self):
                return "Alibaba.com supplier search results"

            def locator(self, selector):
                return FakeLocator()

        self.assertEqual(self.collector.get_blocked_reason(FakePage()), "")

    def test_explicit_login_wall_captcha_and_access_denied_are_blocking(self):
        class FakeLocator:
            def __init__(self, text):
                self.text = text

            def inner_text(self, timeout):
                return self.text

        class FakePage:
            url = "https://www.alibaba.com/trade/search?IndexArea=company_en&SearchText=game%20controller"

            def __init__(self, title, text):
                self._title = title
                self._text = text

            def title(self):
                return self._title

            def locator(self, selector):
                return FakeLocator(self._text)

        self.assertIn(
            "login required",
            self.collector.get_blocked_reason(FakePage("Alibaba.com", "Please sign in to continue")).lower(),
        )
        self.assertIn(
            "captcha",
            self.collector.get_blocked_reason(FakePage("Alibaba.com", "Verify you are human with CAPTCHA")).lower(),
        )
        self.assertIn(
            "access denied",
            self.collector.get_blocked_reason(FakePage("Access Denied", "Forbidden")).lower(),
        )

    def test_is_empty_result_page_detects_empty_marker_from_title_without_body_match(self):
        class FakeLocator:
            def inner_text(self, timeout):
                return "Popular suppliers and featured categories"

        class FakePage:
            url = "https://www.alibaba.com/trade/search?IndexArea=company_en&SearchText=game%20controller"

            def title(self):
                return "No results found for game controller - Alibaba.com"

            def locator(self, selector):
                return FakeLocator()

        self.assertTrue(self.collector.is_empty_result_page(FakePage()))

    def test_is_empty_result_page_detects_empty_marker_from_url_without_body_match(self):
        class FakeLocator:
            def inner_text(self, timeout):
                return "Featured suppliers you may like"

        class FakePage:
            url = (
                "https://www.alibaba.com/trade/search"
                "?IndexArea=company_en&SearchText=game%20controller&noresult=1"
            )

            def title(self):
                return "Alibaba.com supplier search"

            def locator(self, selector):
                return FakeLocator()

        self.assertTrue(self.collector.is_empty_result_page(FakePage()))

    def test_first_page_auth_error_records_diagnostic_before_reraising(self):
        class FakeContext:
            def __init__(self):
                self.closed = False

            def new_page(self):
                return object()

            def close(self):
                self.closed = True

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class AuthFailingCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.context = FakeContext()

            def launch_persistent_context(self, playwright):
                return self.context

            def goto_search_page(self, page, keyword, page_number):
                raise RuntimeError("Alibaba.com access denied")

        collector = AuthFailingCollector()

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            with self.assertRaises(RuntimeError):
                collector.collect("3C鏁扮爜", ["game controller"], 2)

        self.assertTrue(collector.context.closed)
        self.assertEqual(collector.last_error_message, "Alibaba.com access denied")
        self.assertIn("keyword=game controller", collector.last_collect_diagnostic)
        self.assertIn("parsed_cards=0", collector.last_collect_diagnostic)
        self.assertIn("preserved_after_error=Alibaba.com access denied", collector.last_collect_diagnostic)

    def test_context_closes_when_new_page_raises(self):
        class NewPageFailingContext:
            def __init__(self):
                self.closed = False

            def new_page(self):
                raise RuntimeError("new page failed")

            def close(self):
                self.closed = True

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class NewPageFailingCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.context = NewPageFailingContext()

            def launch_persistent_context(self, playwright):
                return self.context

        collector = NewPageFailingCollector()

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            with self.assertRaises(RuntimeError):
                collector.collect("3C鏁扮爜", ["game controller"], 2)

        self.assertTrue(collector.context.closed)

    def test_collect_detects_captcha_that_appears_after_scroll_before_extracting_cards(self):
        class FakeLocator:
            def __init__(self, page):
                self.page = page

            def inner_text(self, timeout):
                return self.page.body_text

        class FakePage:
            url = "https://www.alibaba.com/trade/search?IndexArea=company_en&SearchText=phone%20case"

            def __init__(self):
                self.body_text = "Alibaba.com supplier list\nGuangdong suppliers"

            def title(self):
                return "Alibaba.com supplier search results"

            def locator(self, selector):
                return FakeLocator(self)

        class FakeContext:
            def __init__(self):
                self.closed = False
                self.page = FakePage()

            def new_page(self):
                return self.page

            def close(self):
                self.closed = True

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class DelayedCaptchaCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.context = FakeContext()
                self.extract_called = False

            def launch_persistent_context(self, playwright):
                return self.context

            def goto_search_page(self, page, keyword, page_number):
                self.assert_public_page_allowed(page)

            def scroll_result_page_to_load(self, page):
                page.body_text = "Verify you are human with CAPTCHA"

            def extract_raw_item_list(self, page):
                self.extract_called = True
                return []

        collector = DelayedCaptchaCollector()

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            with self.assertRaisesRegex(RuntimeError, "Alibaba.com CAPTCHA required"):
                collector.collect("Other", ["phone case"], 1)

        self.assertTrue(collector.context.closed)
        self.assertFalse(collector.extract_called)
        self.assertEqual(collector.last_error_message, "Alibaba.com CAPTCHA required")

    def test_extract_raw_item_list_uses_supplier_specific_selectors_and_raw_fields(self):
        raw_item = self.build_raw_item(use_brief_keys=True)

        class FakePage:
            def __init__(self):
                self.script = ""

            def evaluate(self, script):
                self.script = script
                return [raw_item]

        page = FakePage()

        result_list = self.collector.extract_raw_item_list(page)

        self.assertEqual(result_list, [raw_item])
        self.assertNotIn("document.querySelectorAll('div, li, section, article')", page.script)
        self.assertIn("supplier-card", page.script)
        self.assertIn('a[href*=".en.alibaba.com"]', page.script)
        self.assertIn("companyName", result_list[0])
        self.assertIn("locationText", result_list[0])
        self.assertIn("mainProducts", result_list[0])
        self.assertIn("badgeTextList", result_list[0])
        self.assertIn("profileUrl", result_list[0])

    def test_extract_raw_item_list_walks_up_from_supplier_link_when_card_class_changes(self):
        raw_item = self.build_raw_item(use_brief_keys=True)

        class FakePage:
            def __init__(self):
                self.script = ""

            def evaluate(self, script):
                self.script = script
                return [raw_item]

        page = FakePage()

        result_list = self.collector.extract_raw_item_list(page)

        self.assertEqual(result_list, [raw_item])
        self.assertIn("findCardFromAnchor", page.script)
        self.assertIn("parentElement", page.script)
        self.assertIn("extractCompanyName", page.script)

    def test_collect_preserves_accumulated_leads_after_later_non_auth_page_error(self):
        raw_item = self.build_raw_item(use_brief_keys=True)

        class FakeContext:
            def __init__(self):
                self.closed = False

            def new_page(self):
                return object()

            def close(self):
                self.closed = True

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class PreservingCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.context = FakeContext()
                self.page_call_list = []

            def launch_persistent_context(self, playwright):
                return self.context

            def goto_search_page(self, page, keyword, page_number):
                self.page_call_list.append((keyword, page_number))
                if page_number == 2:
                    raise RuntimeError("temporary page parser failure")

            def extract_raw_item_list(self, page):
                return [raw_item]

            def wait_between_page(self):
                return None

        collector = PreservingCollector()

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect("3C鏁扮爜", ["game controller"], 2)

        self.assertEqual(
            collector.page_call_list,
            [("Guangdong game controller", 1), ("Guangdong game controller", 2)],
        )
        self.assertTrue(collector.context.closed)
        self.assertEqual(len(result_list), 1)
        self.assertEqual(result_list[0].suspected_company_name, "Shenzhen Cico Technology Co., Ltd.")
        self.assertIn("parsed_cards=1", collector.last_collect_diagnostic)
        self.assertIn("guangdong_passes=1", collector.last_collect_diagnostic)
        self.assertIn("keyword_relevance_passes=1", collector.last_collect_diagnostic)
        self.assertIn("keyword=game controller", collector.last_collect_diagnostic)

    def test_collect_keeps_scanning_until_selected_city_limit_is_reached(self):
        wrong_city_item = self.build_raw_item(
            company_name_en="Wuzhou Dengfeng Jewelry Co., Ltd.",
            location_text="Wuzhou, Guangxi, China",
            profile_url="https://wuzhou-example.en.alibaba.com/",
            use_brief_keys=True,
        )
        target_city_item = self.build_raw_item(
            company_name_en="Guangzhou Victory Jewelry Co., Ltd.",
            location_text="Guangzhou, Guangdong, China",
            profile_url="https://guangzhou-example.en.alibaba.com/",
            use_brief_keys=True,
        )

        class FakeContext:
            def new_page(self):
                return object()

            def close(self):
                return None

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class CityAwareCollector(AlibabaInternationalSupplierCollector):
            def launch_persistent_context(self, playwright):
                return FakeContext()

            def goto_search_page(self, page, keyword, page_number):
                return None

            def scroll_result_page_to_load(self, page):
                return None

            def extract_raw_item_list(self, page):
                return [wrong_city_item, target_city_item]

        collector = CityAwareCollector()
        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect(
                "珠宝",
                ["silver jewelry"],
                1,
                target_city="广州市",
            )

        self.assertEqual(len(result_list), 1)
        self.assertEqual(
            result_list[0].suspected_company_name,
            "Guangzhou Victory Jewelry Co., Ltd.",
        )
        self.assertEqual(result_list[0].region_text, "Guangzhou, Guangdong, China")

    def test_collect_scans_past_historical_pages_until_new_limit_is_reached(self):
        historical_item_list = [
            self.build_raw_item(
                company_name_en=f"Guangzhou Historical Supplier {index} Co., Ltd.",
                location_text="Guangzhou, Guangdong, China",
                profile_url=f"https://historical-{index}.en.alibaba.com/company_profile.html",
                use_brief_keys=True,
            )
            for index in range(1, 4)
        ]
        new_item = self.build_raw_item(
            company_name_en="Guangzhou Newly Discovered Supplier Co., Ltd.",
            location_text="Guangzhou, Guangdong, China",
            profile_url="https://newly-discovered.en.alibaba.com/company_profile.html",
            use_brief_keys=True,
        )

        class FakeContext:
            def new_page(self):
                return object()

            def close(self):
                return None

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class HistoricalPageCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.current_page_number = 0
                self.page_call_list = []

            def launch_persistent_context(self, playwright):
                return FakeContext()

            def goto_search_page(self, page, keyword, page_number):
                self.current_page_number = page_number
                self.page_call_list.append((keyword, page_number))

            def scroll_result_page_to_load(self, page):
                return None

            def extract_raw_item_list(self, page):
                if self.current_page_number <= len(historical_item_list):
                    return [historical_item_list[self.current_page_number - 1]]
                return [new_item]

            def wait_between_page(self):
                return None

        collector = HistoricalPageCollector()
        collector.set_existing_lead_identity_list(
            [
                {
                    "company_name": item["companyName"],
                    "suspected_company_name": "",
                    "profile_url": item["profileUrl"],
                    "shop_url": "",
                }
                for item in historical_item_list
            ]
        )

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect(
                "珠宝",
                ["silver jewelry"],
                1,
                target_city="广州市",
            )

        self.assertEqual(len(result_list), 1)
        self.assertEqual(
            result_list[0].suspected_company_name,
            "Guangzhou Newly Discovered Supplier Co., Ltd.",
        )
        self.assertEqual(
            collector.page_call_list,
            [
                ("Guangzhou silver jewelry", 1),
                ("Guangzhou silver jewelry", 2),
                ("Guangzhou silver jewelry", 3),
                ("Guangzhou silver jewelry", 4),
            ],
        )
        self.assertEqual(collector.last_existing_skip_count, 3)

    def test_collect_stops_current_search_when_next_page_repeats_same_cards(self):
        repeated_item = self.build_raw_item(
            company_name_en="Guangzhou Repeated Supplier Co., Ltd.",
            location_text="Guangzhou, Guangdong, China",
            profile_url="https://repeated.en.alibaba.com/company_profile.html",
            use_brief_keys=True,
        )

        class FakeContext:
            def new_page(self):
                return object()

            def close(self):
                return None

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class RepeatedPageCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.page_call_list = []

            def launch_persistent_context(self, playwright):
                return FakeContext()

            def goto_search_page(self, page, keyword, page_number):
                self.page_call_list.append((keyword, page_number))

            def scroll_result_page_to_load(self, page):
                return None

            def extract_raw_item_list(self, page):
                return [repeated_item]

            def wait_between_page(self):
                return None

        collector = RepeatedPageCollector()
        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect(
                "珠宝",
                ["silver jewelry"],
                2,
                target_city="广州市",
            )

        self.assertEqual(len(result_list), 1)
        self.assertEqual(
            collector.page_call_list,
            [
                ("Guangzhou silver jewelry", 1),
                ("Guangzhou silver jewelry", 2),
                ("silver jewelry", 1),
                ("silver jewelry", 2),
            ],
        )
        self.assertEqual(collector.last_repeated_page_count, 2)

    def test_collect_fallback_keyword_still_uses_original_selected_city(self):
        wrong_city_item = self.build_raw_item(
            company_name_en="Shenzhen Wrong City Technology Co., Ltd.",
            location_text="Shenzhen, Guangdong, China",
            profile_url="https://shenzhen-wrong-city.en.alibaba.com/",
            use_brief_keys=True,
        )
        target_city_item = self.build_raw_item(
            company_name_en="Guangzhou Target Technology Co., Ltd.",
            location_text="Guangzhou, Guangdong, China",
            profile_url="https://guangzhou-target-city.en.alibaba.com/",
            use_brief_keys=True,
        )

        class FakeContext:
            def new_page(self):
                return object()

            def close(self):
                return None

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class FallbackCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.current_search_text = ""

            def launch_persistent_context(self, playwright):
                return FakeContext()

            def goto_search_page(self, page, keyword, page_number):
                self.current_search_text = keyword

            def scroll_result_page_to_load(self, page):
                return None

            def extract_raw_item_list(self, page):
                if self.current_search_text.startswith("Guangzhou "):
                    return []
                return [wrong_city_item, target_city_item]

            def wait_between_page(self):
                return None

        collector = FallbackCollector()
        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect(
                "3C数码",
                ["game controller"],
                1,
                target_city="广州市",
            )

        self.assertEqual(len(result_list), 1)
        self.assertEqual(
            result_list[0].suspected_company_name,
            "Guangzhou Target Technology Co., Ltd.",
        )

    def test_collect_preserves_accumulated_leads_when_later_page_requires_captcha(self):
        raw_item = self.build_raw_item(use_brief_keys=True)

        class FakeContext:
            def __init__(self):
                self.closed = False

            def new_page(self):
                return object()

            def close(self):
                self.closed = True

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class CaptchaAfterFirstPageCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.context = FakeContext()
                self.page_call_list = []

            def launch_persistent_context(self, playwright):
                return self.context

            def goto_search_page(self, page, keyword, page_number):
                self.page_call_list.append((keyword, page_number))
                if page_number == 2:
                    raise RuntimeError("Alibaba.com CAPTCHA required")

            def extract_raw_item_list(self, page):
                return [raw_item]

            def wait_between_page(self):
                return None

        collector = CaptchaAfterFirstPageCollector()

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect("3C数码", ["game controller"], 2)

        self.assertEqual(
            collector.page_call_list,
            [("Guangdong game controller", 1), ("Guangdong game controller", 2)],
        )
        self.assertTrue(collector.context.closed)
        self.assertEqual(len(result_list), 1)
        self.assertEqual(result_list[0].suspected_company_name, "Shenzhen Cico Technology Co., Ltd.")
        self.assertIn("preserved_after_error=Alibaba.com CAPTCHA required", collector.last_collect_diagnostic)

    def test_collect_preserves_accumulated_leads_after_later_playwright_error(self):
        raw_item = self.build_raw_item(use_brief_keys=True)

        class FakeContext:
            def __init__(self):
                self.closed = False

            def new_page(self):
                return object()

            def close(self):
                self.closed = True

        class FakePlaywright:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class PreservingCollector(AlibabaInternationalSupplierCollector):
            def __init__(self):
                super().__init__()
                self.context = FakeContext()
                self.page_call_list = []

            def launch_persistent_context(self, playwright):
                return self.context

            def goto_search_page(self, page, keyword, page_number):
                self.page_call_list.append((keyword, page_number))
                if page_number == 2:
                    raise collector_module.PlaywrightError("browser page closed unexpectedly")

            def extract_raw_item_list(self, page):
                return [raw_item]

            def wait_between_page(self):
                return None

        collector = PreservingCollector()

        with patch(
            "app.service.alibaba_international_collector.sync_playwright",
            return_value=FakePlaywright(),
        ):
            result_list = collector.collect("3C鏁扮爜", ["game controller"], 2)

        self.assertEqual(
            collector.page_call_list,
            [("Guangdong game controller", 1), ("Guangdong game controller", 2)],
        )
        self.assertTrue(collector.context.closed)
        self.assertEqual(len(result_list), 1)
        self.assertIn("preserved_after_error=browser page closed unexpectedly", collector.last_collect_diagnostic)


if __name__ == "__main__":
    unittest.main()
