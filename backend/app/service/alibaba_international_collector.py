import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from app.core.config import get_config
from app.core.constant import SOURCE_TYPE_ALIBABA_INTERNATIONAL
from app.model.schema import CollectedLeadDTO
from app.util.browser_profile_util import list_browser_profile_process_id

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None


def _normalize_identity_text(text: str) -> str:
    return re.sub(r"[\s\W_]+", " ", (text or "").casefold()).strip()


BADGE_WHITELIST = (
    "Verified Supplier",
    "Gold Supplier",
    "Custom Manufacturer",
    "Multispecialty Supplier",
)
BADGE_WHITELIST_LOOKUP = {_normalize_identity_text(badge): badge for badge in BADGE_WHITELIST}
GUANGDONG_CITY_SEARCH_TEXT_MAP = {
    "广东省": "Guangdong",
    "广州市": "Guangzhou",
    "深圳市": "Shenzhen",
    "珠海市": "Zhuhai",
    "汕头市": "Shantou",
    "佛山市": "Foshan",
    "韶关市": "Shaoguan",
    "湛江市": "Zhanjiang",
    "肇庆市": "Zhaoqing",
    "江门市": "Jiangmen",
    "茂名市": "Maoming",
    "惠州市": "Huizhou",
    "梅州市": "Meizhou",
    "汕尾市": "Shanwei",
    "河源市": "Heyuan",
    "阳江市": "Yangjiang",
    "清远市": "Qingyuan",
    "东莞市": "Dongguan",
    "中山市": "Zhongshan",
    "潮州市": "Chaozhou",
    "揭阳市": "Jieyang",
    "云浮市": "Yunfu",
}
GUANGDONG_LOCATION_TOKEN_LIST = tuple(
    city_name.casefold() for city_name in GUANGDONG_CITY_SEARCH_TEXT_MAP.values()
)
DEFAULT_GUANGDONG_TARGET_CITY = "广东省"
MAX_SEARCH_PAGE_COUNT = 50
KEYWORD_STOP_WORD_SET = {
    "a",
    "an",
    "and",
    "china",
    "co",
    "company",
    "custom",
    "factory",
    "for",
    "from",
    "guangdong",
    "guangzhou",
    "in",
    "international",
    "ltd",
    "manufacturer",
    "of",
    "supplier",
    "shenzhen",
    "the",
    "trade",
    "verified",
}


@dataclass
class AlibabaInternationalCandidate:
    source_keyword: str
    company_name_en: str
    product_name: str
    shop_level: str
    location_text: str
    profile_url: str


class AlibabaInternationalSupplierCollector:
    def __init__(self):
        self.config = get_config()
        self._existing_company_identity_set = set()
        self._existing_profile_url_set = set()
        self._seen_company_identity_set = set()
        self._seen_profile_url_set = set()
        self.reset_collect_diagnostic()

    def reset_collect_diagnostic(self) -> None:
        self.last_collect_diagnostic = ""
        self.last_search_keyword_list = []
        self.last_parsed_card_count = 0
        self.last_guangdong_pass_count = 0
        self.last_keyword_relevance_pass_count = 0
        self.last_lead_count = 0
        self.last_empty_result_count = 0
        self.last_existing_skip_count = 0
        self.last_repeated_page_count = 0
        self.last_page_visit_count = 0
        self.last_error_message = ""

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self._existing_company_identity_set = set()
        self._existing_profile_url_set = set()
        for identity in identity_list or []:
            for field_name in ("company_name", "suspected_company_name"):
                company_identity = self._normalize_company_identity(identity.get(field_name, ""))
                if company_identity:
                    self._existing_company_identity_set.add(company_identity)
            for field_name in ("profile_url", "shop_url"):
                profile_url = self._normalize_profile_url(identity.get(field_name, ""))
                if profile_url:
                    self._existing_profile_url_set.add(profile_url)

    def collect(
        self,
        industry: str,
        keywords: List[str],
        collect_limit: int,
        target_city: str = DEFAULT_GUANGDONG_TARGET_CITY,
    ) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("Playwright is required for Alibaba.com browser collection")
        if collect_limit <= 0:
            raise RuntimeError("Alibaba.com collection limit must be greater than 0")

        self.reset_collect_diagnostic()
        self._seen_company_identity_set = set()
        self._seen_profile_url_set = set()
        clean_keyword_list = self.build_search_keyword_list(industry, keywords)
        self.last_search_keyword_list = clean_keyword_list
        search_plan = self.build_search_plan(clean_keyword_list, target_city)
        result_list: List[CollectedLeadDTO] = []
        dedupe_key_set = set()
        should_stop = False

        with sync_playwright() as playwright:
            context = self.launch_persistent_context(playwright)
            try:
                page = context.new_page()
                for keyword, target_city_item, search_text in search_plan:
                    if should_stop or len(result_list) >= collect_limit:
                        break
                    page_number = 1
                    max_page_count = self.build_max_page_count(collect_limit - len(result_list))
                    page_fingerprint_set = set()
                    while page_number <= max_page_count and len(result_list) < collect_limit:
                        try:
                            self.goto_search_page(page, search_text, page_number)
                            self.scroll_result_page_to_load(page)
                            self.assert_public_page_allowed(page)
                            raw_item_list = self.extract_raw_item_list(page)
                            self.last_page_visit_count += 1
                            if not raw_item_list:
                                self.assert_public_page_allowed(page)
                            page_fingerprint = self.build_raw_item_page_fingerprint(raw_item_list)
                            if page_fingerprint and page_fingerprint in page_fingerprint_set:
                                self.last_repeated_page_count += 1
                                break
                            if page_fingerprint:
                                page_fingerprint_set.add(page_fingerprint)
                            self.last_parsed_card_count += len(raw_item_list)
                            if not raw_item_list and self.is_empty_result_page(page):
                                self.last_empty_result_count += 1
                            for raw_item in raw_item_list:
                                self.record_raw_item_filter_counts(keyword, raw_item)
                                lead = self.build_lead(keyword, industry, raw_item, target_city=target_city_item)
                                if lead is None:
                                    continue
                                location_evidence = " ".join(
                                    filter(
                                        None,
                                        (
                                            lead.region_text,
                                            lead.company_name_en,
                                            lead.suspected_company_name,
                                        ),
                                    )
                                )
                                if not self.is_target_location(location_evidence, target_city):
                                    continue
                                dedupe_key = self.build_dedupe_key(lead)
                                if dedupe_key in dedupe_key_set:
                                    continue
                                dedupe_key_set.add(dedupe_key)
                                result_list.append(lead)
                                if len(result_list) >= collect_limit:
                                    break
                        except (RuntimeError, PlaywrightError) as ex:
                            self.last_error_message = self._trim_visible_text(str(ex))[:180]
                            if not result_list:
                                self.last_lead_count = len(result_list)
                                self.last_collect_diagnostic = self.build_collect_diagnostic()
                                raise
                            should_stop = True
                            break
                        page_number += 1
                        if page_number <= max_page_count and len(result_list) < collect_limit:
                            self.wait_between_page()
            finally:
                context.close()

        self.last_lead_count = len(result_list)
        self.last_collect_diagnostic = self.build_collect_diagnostic()
        return result_list

    def build_search_keyword_list(self, industry: str, keywords: List[str]) -> List[str]:
        keyword_list = []
        for keyword in keywords or []:
            for part in re.split(r"[,，、\n\r]+", keyword or ""):
                clean_keyword = self._trim_visible_text(part)
                if clean_keyword and clean_keyword not in keyword_list:
                    keyword_list.append(clean_keyword)
        if keyword_list:
            return keyword_list
        clean_industry = self._trim_visible_text(industry)
        return [clean_industry] if clean_industry else []

    def build_max_page_count(self, remaining_limit: int) -> int:
        if remaining_limit <= 0:
            return 1
        return MAX_SEARCH_PAGE_COUNT

    def normalize_target_city_list(self, target_city: str) -> List[str]:
        clean_target_city_text = self._trim_visible_text(target_city)
        if clean_target_city_text in ("", "广东", DEFAULT_GUANGDONG_TARGET_CITY):
            return [DEFAULT_GUANGDONG_TARGET_CITY]
        city_list: List[str] = []
        for raw_city in re.split(r"[,，、;/\n\r]+", clean_target_city_text):
            clean_city = self._trim_visible_text(raw_city)
            if clean_city in ("", "广东", DEFAULT_GUANGDONG_TARGET_CITY):
                continue
            if clean_city in GUANGDONG_CITY_SEARCH_TEXT_MAP:
                if clean_city not in city_list:
                    city_list.append(clean_city)
                continue
            city_with_suffix = clean_city if clean_city.endswith("市") else f"{clean_city}市"
            if city_with_suffix in GUANGDONG_CITY_SEARCH_TEXT_MAP and city_with_suffix not in city_list:
                city_list.append(city_with_suffix)
        return city_list or [DEFAULT_GUANGDONG_TARGET_CITY]

    def build_search_plan(self, keyword_list: List[str], target_city: str = DEFAULT_GUANGDONG_TARGET_CITY) -> List[tuple[str, str, str]]:
        search_plan = []
        for keyword in keyword_list:
            seen_search_text_set = set()
            for target_city_item in self.normalize_target_city_list(target_city):
                search_text = self.build_search_text(keyword, target_city_item)
                normalized_search_text = self._normalize_matching_text(search_text)
                if normalized_search_text in seen_search_text_set:
                    continue
                search_plan.append((keyword, target_city_item, search_text))
                seen_search_text_set.add(normalized_search_text)
            clean_keyword = self._trim_visible_text(keyword)
            normalized_keyword = self._normalize_matching_text(clean_keyword)
            if clean_keyword and normalized_keyword not in seen_search_text_set:
                search_plan.append((keyword, DEFAULT_GUANGDONG_TARGET_CITY, clean_keyword))
        return search_plan

    def build_search_url(self, keyword: str, page_number: int) -> str:
        encoded_keyword = quote(self._trim_visible_text(keyword), safe="")
        safe_page_number = max(1, int(page_number or 1))
        return (
            "https://www.alibaba.com/trade/search"
            f"?IndexArea=company_en&SearchText={encoded_keyword}&page={safe_page_number}"
        )

    def build_search_text(self, keyword: str, target_city: str = DEFAULT_GUANGDONG_TARGET_CITY) -> str:
        clean_keyword = self._trim_visible_text(keyword)
        city_search_text = GUANGDONG_CITY_SEARCH_TEXT_MAP.get(
            self._trim_visible_text(target_city),
            GUANGDONG_CITY_SEARCH_TEXT_MAP[DEFAULT_GUANGDONG_TARGET_CITY],
        )
        normalized_keyword = self._normalize_matching_text(clean_keyword)
        if re.search(rf"\b{re.escape(city_search_text.casefold())}\b", normalized_keyword):
            return clean_keyword
        return f"{city_search_text} {clean_keyword}".strip()

    def launch_persistent_context(self, playwright):
        self.assert_browser_profile_available()
        self.config.alibaba_international_user_data_dir.mkdir(parents=True, exist_ok=True)
        context_args = {
            "headless": self.config.alibaba_international_headless,
            "locale": "en-US",
            "viewport": {"width": 1366, "height": 900},
        }
        if self.config.alibaba_international_browser_channel:
            context_args["channel"] = self.config.alibaba_international_browser_channel
        try:
            return playwright.chromium.launch_persistent_context(
                str(self.config.alibaba_international_user_data_dir),
                **context_args,
            )
        except PlaywrightError as ex:
            if "channel" not in context_args or not self.is_browser_channel_unavailable(ex):
                raise RuntimeError(self.build_browser_start_error_message(ex)) from ex
            context_args.pop("channel")
            return playwright.chromium.launch_persistent_context(
                str(self.config.alibaba_international_user_data_dir),
                **context_args,
            )

    def assert_browser_profile_available(self) -> None:
        process_id_list = list_browser_profile_process_id(self.config.alibaba_international_user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"Alibaba.com browser profile is already in use by process: {process_text}")

    def is_browser_channel_unavailable(self, ex: PlaywrightError) -> bool:
        return "not found" in str(ex).lower() or "executable doesn't exist" in str(ex).lower()

    def build_browser_start_error_message(self, ex: PlaywrightError) -> str:
        message = self._trim_visible_text(str(ex))
        if len(message) > 220:
            message = f"{message[:220]}..."
        return f"Alibaba.com browser failed to start: {message}"

    def goto_search_page(self, page, keyword: str, page_number: int) -> None:
        search_url = self.build_search_url(keyword, page_number)
        try:
            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=self.config.alibaba_international_page_timeout_ms,
            )
            page.wait_for_timeout(1600)
        except PlaywrightTimeoutError:
            pass
        except PlaywrightError as ex:
            if not self.is_recoverable_navigation_error(ex):
                raise RuntimeError(str(ex)) from ex
            page.wait_for_timeout(1200)
        self.assert_public_page_allowed(page)

    def is_recoverable_navigation_error(self, ex: PlaywrightError) -> bool:
        message = str(ex).lower()
        return "execution context was destroyed" in message or "navigation" in message

    def scroll_result_page_to_load(self, page) -> None:
        if not hasattr(page, "evaluate"):
            return
        for _ in range(4):
            page.evaluate("() => window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
            page.wait_for_timeout(700)

    def extract_raw_item_list(self, page) -> List[Dict]:
        return page.evaluate(
            """
            () => {
              const supplierCardSelector = [
                '[data-spm*="supplier-card"]',
                '[class*="supplier-card"]',
                '[class*="supplierCard"]',
                '[class*="supplier-list"]',
                '[class*="factory-card"]',
                '[class*="search-card"]',
                '[class*="organic-gallery-offer"]',
                '[data-testid*="supplier"]'
              ].join(', ');
              const supplierAnchorSelector = [
                'a[href*=".en.alibaba.com"]',
                'a[href*="/company_profile"]',
                'a[href*="/supplier"]'
              ].join(', ');
              const isVisible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && rect.width > 180
                  && rect.height > 80;
              };
              const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
              const isNoiseLine = (value) => {
                return !value
                  || value.length > 90
                  || /verified|supplier|response|rate|years?|yrs?|trade assurance|contact|chat now|view more|min\\.? order|price|piece|set|company profile|transaction/i.test(value)
                  || /^(US\\s*\\$|\\$|¥|MOQ|FOB)/i.test(value)
                  || /^[\\d\\s.,%+-]+$/.test(value);
              };
              const extractProducts = (text, companyName = '') => {
                const match = text.match(/(?:Main Products|Products)\\s*:?\\s*([\\s\\S]{0,320}?)(?:Business Type|Total Revenue|Year Established|Verified|Supplier|Response Rate|$)/i);
                const productText = match ? match[1] : text;
                return productText
                  .split(/[;,|•\\n]/)
                  .map(clean)
                  .filter((value) => value && value !== companyName && !isNoiseLine(value))
                  .slice(0, 8);
              };
              const extractLocation = (text) => {
                const lines = text.split(/[\\n|]/).map(clean).filter(Boolean);
                return lines.find((line) => /guangdong|guangzhou|shenzhen|zhuhai|shantou|foshan|shaoguan|zhanjiang|zhaoqing|jiangmen|maoming|huizhou|meizhou|shanwei|heyuan|yangjiang|qingyuan|dongguan|zhongshan|chaozhou|jieyang|yunfu/i.test(line)) || '';
              };
              const findCardFromAnchor = (anchor) => {
                const closestCard = anchor.closest(supplierCardSelector);
                if (closestCard) return closestCard;
                let node = anchor.parentElement;
                let best = null;
                for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                  const rect = node.getBoundingClientRect();
                  const text = clean(node.innerText);
                  if (rect.width >= 220 && rect.height >= 80 && text.length >= 20) {
                    best = node;
                  }
                  if (best && (text.length >= 500 || rect.height >= 260)) {
                    break;
                  }
                }
                return best;
              };
              const extractCompanyName = (card, profileLink) => {
                const text = card.innerText || '';
                const nodeList = Array.from(card.querySelectorAll(`${supplierAnchorSelector}, h1, h2, h3, h4`));
                const valueList = nodeList
                  .map((element) => clean(element.innerText || element.getAttribute('title') || element.getAttribute('aria-label') || ''))
                  .filter(Boolean);
                const companyValue = valueList.find((value) => /[a-z]/i.test(value) && /\\b(co\\.?|company|ltd\\.?|limited|factory|manufacturer|trading|group)\\b/i.test(value));
                if (companyValue) return companyValue;
                const lineList = text.split(/[\\n|]/).map(clean).filter(Boolean);
                const companyLine = lineList.find((line) => /[a-z]/i.test(line) && /\\b(co\\.?|company|ltd\\.?|limited|factory|manufacturer|trading|group)\\b/i.test(line));
                if (companyLine) return companyLine;
                return clean((profileLink && (profileLink.innerText || profileLink.getAttribute('title') || profileLink.getAttribute('aria-label'))) || '');
              };
              const explicitCardSet = new Set(Array.from(document.querySelectorAll(supplierCardSelector)));
              Array.from(document.querySelectorAll(supplierAnchorSelector)).forEach((anchor) => {
                const card = findCardFromAnchor(anchor);
                if (card) {
                  explicitCardSet.add(card);
                }
              });
              const cardList = Array.from(explicitCardSet)
                .filter(isVisible)
                .filter((element) => clean(element.innerText).length >= 20 && element.querySelector(supplierAnchorSelector))
                .slice(0, 120);
              return cardList.map((card) => {
                const text = card.innerText || '';
                const profileLink = card.querySelector(supplierAnchorSelector);
                const badgeTextList = Array.from(card.querySelectorAll('[class*="badge"], [class*="verify"], [class*="supplier"]'))
                  .map((element) => clean(element.innerText))
                  .filter(Boolean)
                  .slice(0, 12);
                const companyName = extractCompanyName(card, profileLink);
                return {
                  companyName,
                  locationText: extractLocation(text),
                  mainProducts: extractProducts(text, companyName),
                  badgeTextList,
                  profileUrl: (profileLink && profileLink.href) || ''
                };
              });
            }
            """
        )

    def assert_public_page_allowed(self, page) -> None:
        blocked_reason = self.get_blocked_reason(page)
        if blocked_reason:
            raise RuntimeError(blocked_reason)

    def get_blocked_reason(self, page) -> str:
        page_url = self._safe_page_url(page).lower()
        page_title = self._safe_page_title(page).lower()
        page_text = self._safe_page_text(page).lower()[:5000]
        title_and_text = f"{page_title} {page_text}"
        if any(token in page_url for token in ("passport.alibaba", "/login", "/signin", "/sign-in")):
            return "Alibaba.com login required"
        if any(
            token in title_and_text
            for token in (
                "please sign in to continue",
                "sign in to continue",
                "please login to continue",
                "please log in to continue",
                "login to continue",
                "login required",
                "sign in required",
            )
        ):
            return "Alibaba.com login required"
        merged_text = f"{page_url} {page_title} {page_text}"
        if any(token in merged_text for token in ("captcha", "verify you are human", "security check")):
            return "Alibaba.com CAPTCHA required"
        if any(token in merged_text for token in ("access denied", "forbidden", "blocked")):
            return "Alibaba.com access denied"
        return ""

    def is_empty_result_page(self, page) -> bool:
        page_markers = " ".join(
            filter(
                None,
                (
                    self._normalize_matching_text(self._safe_page_url(page)),
                    self._normalize_matching_text(self._safe_page_title(page)),
                    self._normalize_matching_text(self._safe_page_text(page)[:5000]),
                ),
            )
        )
        return any(
            token in page_markers
            for token in (
                "no results found",
                "did not match any products",
                "we couldn't find any matches",
                "0 results",
                "noresult 1",
            )
        )

    def _safe_page_url(self, page) -> str:
        return self._trim_visible_text(getattr(page, "url", ""))

    def _safe_page_title(self, page) -> str:
        try:
            return self._trim_visible_text(page.title())
        except Exception:
            return ""

    def _safe_page_text(self, page) -> str:
        if not hasattr(page, "locator"):
            return ""
        try:
            return self._trim_visible_text(page.locator("body").inner_text(timeout=1500))
        except Exception:
            return ""

    def is_auth_or_access_error_message(self, message: str) -> bool:
        normalized_message = message.lower()
        return any(
            token in normalized_message
            for token in ("login", "captcha", "access denied", "security check")
        )

    def wait_between_page(self) -> None:
        wait_seconds = max(0.0, float(self.config.alibaba_international_request_interval_seconds))
        if wait_seconds:
            time.sleep(wait_seconds)

    def record_raw_item_filter_counts(self, keyword: str, raw_item: dict) -> None:
        location_text = self._trim_visible_text(
            self._get_first_value(raw_item, "location_text", "locationText", "location")
        )
        if self.is_guangdong_location(location_text):
            self.last_guangdong_pass_count += 1
        product_list = self._coerce_text_list(
            self._get_first_value(raw_item, "main_products", "mainProducts", "products")
        )
        if product_list and self._is_product_list_relevant(keyword, product_list):
            self.last_keyword_relevance_pass_count += 1

    def build_dedupe_key(self, lead: CollectedLeadDTO) -> str:
        normalized_profile_url = self._normalize_profile_url(lead.profile_url or lead.shop_url)
        if normalized_profile_url:
            return f"url:{normalized_profile_url}"
        return f"company:{self._normalize_company_identity(lead.company_name_en or lead.suspected_company_name)}"

    def build_raw_item_page_fingerprint(self, raw_item_list: List[Dict]) -> str:
        identity_list = []
        for raw_item in raw_item_list or []:
            profile_url = self._normalize_profile_url(
                self._get_first_value(raw_item, "profile_url", "profileUrl", "href")
            )
            company_identity = self._normalize_company_identity(
                self._get_first_value(
                    raw_item,
                    "company_name_en",
                    "companyNameEn",
                    "companyName",
                    "company",
                )
            )
            identity = f"url:{profile_url}" if profile_url else f"company:{company_identity}"
            if identity not in ("url:", "company:"):
                identity_list.append(identity)
        return "|".join(sorted(set(identity_list)))

    def build_lead(
        self,
        keyword: str,
        industry: str,
        raw_item: dict,
        target_city: str = "广东省",
    ) -> Optional[CollectedLeadDTO]:
        candidate = self.build_candidate(keyword, raw_item, industry, target_city=target_city)
        if candidate is None:
            return None
        return CollectedLeadDTO(
            source_type=SOURCE_TYPE_ALIBABA_INTERNATIONAL,
            source_keyword=candidate.source_keyword,
            industry=industry,
            suspected_company_name=candidate.company_name_en,
            company_name_en=candidate.company_name_en,
            product_name=candidate.product_name,
            shop_level=candidate.shop_level,
            region_text=candidate.location_text,
            shop_url=candidate.profile_url,
            profile_url=candidate.profile_url,
        )

    def build_collect_diagnostic(self) -> str:
        keyword_text = " | ".join(self.last_search_keyword_list)
        if len(self.last_search_keyword_list) == 1:
            keyword_part = f"keyword={keyword_text}"
        else:
            keyword_part = f"keywords={keyword_text}"
        parts = [
            keyword_part,
            f"parsed_cards={self.last_parsed_card_count}",
            f"guangdong_passes={self.last_guangdong_pass_count}",
            f"keyword_relevance_passes={self.last_keyword_relevance_pass_count}",
            f"leads={self.last_lead_count}",
            f"pages={self.last_page_visit_count}",
        ]
        if self.last_existing_skip_count:
            parts.append(f"existing_skips={self.last_existing_skip_count}")
        if self.last_repeated_page_count:
            parts.append(f"repeated_pages={self.last_repeated_page_count}")
        if self.last_empty_result_count:
            parts.append(f"empty_results={self.last_empty_result_count}")
        if self.last_error_message:
            parts.append(f"preserved_after_error={self.last_error_message}")
        return "; ".join(parts)

    def build_candidate(
        self,
        keyword: str,
        raw_item: dict,
        industry: str,
        target_city: str = "广东省",
    ) -> Optional[AlibabaInternationalCandidate]:
        del industry
        company_name_en = self._trim_visible_text(
            self._get_first_value(
                raw_item,
                "company_name_en",
                "companyNameEn",
                "companyName",
                "company",
            )
        )
        if not self._is_english_company_name(company_name_en):
            return None

        location_text = self._trim_visible_text(
            self._get_first_value(raw_item, "location_text", "locationText", "location")
        )

        product_list = self._coerce_text_list(
            self._get_first_value(raw_item, "main_products", "mainProducts", "products")
        )

        profile_url = self._trim_visible_text(
            self._get_first_value(raw_item, "profile_url", "profileUrl", "href")
        )
        normalized_company_identity = self._normalize_company_identity(company_name_en)
        normalized_profile_url = self._normalize_profile_url(profile_url)
        if (
            normalized_company_identity
            and normalized_company_identity in self._existing_company_identity_set
        ) or (
            normalized_profile_url
            and normalized_profile_url in self._existing_profile_url_set
        ):
            self.last_existing_skip_count += 1
            return None
        if normalized_company_identity and normalized_company_identity in self._seen_company_identity_set:
            return None
        if normalized_profile_url and normalized_profile_url in self._seen_profile_url_set:
            return None

        shop_level_list = self._filter_whitelisted_badges(
            self._coerce_text_list(
                self._get_first_value(raw_item, "badges", "badgeTextList", "labels")
            )
        )

        candidate = AlibabaInternationalCandidate(
            source_keyword=keyword,
            company_name_en=company_name_en,
            product_name="; ".join(product_list),
            shop_level="; ".join(shop_level_list),
            location_text=location_text,
            profile_url=profile_url,
        )
        if normalized_company_identity:
            self._seen_company_identity_set.add(normalized_company_identity)
        if normalized_profile_url:
            self._seen_profile_url_set.add(normalized_profile_url)
        return candidate

    def is_guangdong_location(self, text: str) -> bool:
        normalized_text = self._normalize_matching_text(text)
        if not normalized_text:
            return False
        return any(token in normalized_text for token in GUANGDONG_LOCATION_TOKEN_LIST)

    def is_target_location(self, text: str, target_city: str = DEFAULT_GUANGDONG_TARGET_CITY) -> bool:
        if not self.is_guangdong_location(text):
            return False
        target_city_list = self.normalize_target_city_list(target_city)
        if target_city_list == [DEFAULT_GUANGDONG_TARGET_CITY]:
            return True
        normalized_text = self._normalize_matching_text(text)
        for clean_target_city in target_city_list:
            city_search_text = GUANGDONG_CITY_SEARCH_TEXT_MAP.get(clean_target_city)
            if city_search_text and re.search(rf"\b{re.escape(city_search_text.casefold())}\b", normalized_text):
                return True
        return False

    def _get_first_value(self, raw_item: dict, *field_names: str):
        for field_name in field_names:
            value = raw_item.get(field_name)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, tuple)) and not value:
                continue
            return value
        return ""

    def _coerce_text_list(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            source_list = re.split(r"[;\n|]+", value)
        elif isinstance(value, Iterable):
            source_list = list(value)
        else:
            source_list = [value]

        clean_item_list = []
        for item in source_list:
            clean_item = self._trim_visible_text(item)
            if clean_item:
                clean_item_list.append(clean_item)
        return clean_item_list

    def _filter_whitelisted_badges(self, badge_list: list[str]) -> list[str]:
        keep_list = []
        seen_badge_set = set()
        for badge in badge_list:
            normalized_badge = self._normalize_matching_text(badge)
            whitelist_badge = BADGE_WHITELIST_LOOKUP.get(normalized_badge)
            if not whitelist_badge or normalized_badge in seen_badge_set:
                continue
            keep_list.append(badge)
            seen_badge_set.add(normalized_badge)
        return keep_list

    def _is_product_list_relevant(self, keyword: str, product_list: list[str]) -> bool:
        keyword_token_set = self._extract_match_tokens(keyword)
        if not keyword_token_set:
            return True
        product_token_set = set()
        for product_name in product_list:
            product_token_set.update(self._extract_match_tokens(product_name))
        return bool(keyword_token_set & product_token_set)

    def _extract_match_tokens(self, text: str) -> set[str]:
        normalized_text = self._normalize_matching_text(text)
        token_set = set()
        for token in re.findall(r"[a-z0-9]+", normalized_text):
            singular_token = self._singularize_token(token)
            if len(singular_token) < 2 or singular_token in KEYWORD_STOP_WORD_SET:
                continue
            token_set.add(singular_token)
        return token_set

    def _is_english_company_name(self, company_name_en: str) -> bool:
        if not company_name_en:
            return False
        if not re.search(r"[A-Za-z]", company_name_en):
            return False
        normalized_company_identity = self._normalize_company_identity(company_name_en)
        return len(normalized_company_identity) >= 6

    def _normalize_company_identity(self, text: str) -> str:
        normalized_text = self._normalize_matching_text(text)
        return re.sub(r"[^a-z0-9]", "", normalized_text)

    def _normalize_profile_url(self, profile_url: str) -> str:
        if not profile_url:
            return ""
        parts = urlsplit(profile_url.strip())
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/")
        return urlunsplit((scheme, netloc, path, "", ""))

    def _normalize_matching_text(self, text: str) -> str:
        return _normalize_identity_text(text)

    def _trim_visible_text(self, value) -> str:
        return str(value or "").strip()

    def _singularize_token(self, token: str) -> str:
        if len(token) > 4 and token.endswith("ies"):
            return token[:-3] + "y"
        if len(token) > 3 and token.endswith("es"):
            return token[:-2]
        if len(token) > 3 and token.endswith("s"):
            return token[:-1]
        return token
