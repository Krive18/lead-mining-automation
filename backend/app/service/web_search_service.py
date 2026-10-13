import html
import json
import logging
import os
import re
import ssl
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from app.core.config import get_config

logger = logging.getLogger(__name__)

BINARY_URL_SUFFIX_LIST = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
)
SKIP_HOST_TOKEN_LIST = (
    "baidu.com/link",
    "translate.google",
    "webcache",
)


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass
class PublicPageDocument:
    title: str
    url: str
    snippet: str
    text: str
    source_query: str = ""


class PublicWebSearchService:
    def __init__(self):
        self.config = get_config()

    def search(self, query: str, limit: int) -> List[WebSearchResult]:
        if self.config.web_search_provider == "bing_api" and self.config.web_search_api_key:
            return self.search_with_bing_api(query, limit)
        if self.config.web_search_provider == "bing_html":
            return self.search_with_fallback_chain(
                query,
                limit,
                [self.search_with_bing_html, self.search_with_duckduckgo_html, self.search_with_bing_rss],
            )
        if self.config.web_search_provider == "bing_rss":
            return self.search_with_fallback_chain(
                query,
                limit,
                [self.search_with_bing_rss, self.search_with_duckduckgo_html, self.search_with_bing_html],
            )
        if self.config.web_search_provider == "so_html":
            return self.search_with_fallback_chain(
                query,
                limit,
                [
                    self.search_with_so_html,
                    self.search_with_sogou_html,
                    self.search_with_duckduckgo_html,
                    self.search_with_bing_html,
                    self.search_with_bing_rss,
                ],
            )
        return self.search_with_fallback_chain(
            query,
            limit,
            [
                self.search_with_so_html,
                self.search_with_sogou_html,
                self.search_with_duckduckgo_html,
                self.search_with_bing_html,
                self.search_with_bing_rss,
            ],
        )

    def search_with_fallback_chain(self, query: str, limit: int, search_fn_list) -> List[WebSearchResult]:
        result_list: List[WebSearchResult] = []
        error_message_list = []
        attempted_provider_count = 0
        for search_fn in search_fn_list:
            attempted_provider_count += 1
            try:
                current_result_list = search_fn(query, limit)
            except Exception as ex:
                logger.warning("Web search provider failed, query=%s, provider=%s, error=%s", query, search_fn.__name__, ex)
                error_message_list.append(f"{search_fn.__name__}: {ex}")
                continue
            current_result_list = self.filter_relevant_result_list(query, current_result_list)
            if not current_result_list:
                logger.info("Web search provider returned empty, query=%s, provider=%s", query, search_fn.__name__)
                continue
            result_list.extend(current_result_list)
            result_list = self.dedupe_result_list(result_list)
            if len(result_list) >= limit:
                break
        if result_list:
            return result_list[:limit]
        if error_message_list and len(error_message_list) >= attempted_provider_count:
            raise RuntimeError("; ".join(error_message_list))
        return []

    def search_with_fallback(self, query: str, limit: int, primary_search, fallback_search) -> List[WebSearchResult]:
        try:
            primary_result_list = primary_search(query, limit)
            if primary_result_list:
                return primary_result_list
            logger.warning("Primary web search returned empty, query=%s", query)
        except Exception as primary_ex:
            logger.warning("Primary web search failed, query=%s, error=%s", query, primary_ex)
            try:
                return fallback_search(query, limit)
            except Exception as fallback_ex:
                raise RuntimeError(f"{primary_ex}; fallback search failed: {fallback_ex}") from fallback_ex
        return fallback_search(query, limit)

    def search_with_duckduckgo_html(self, query: str, limit: int) -> List[WebSearchResult]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(
            url,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        try:
            with self.open_request(request) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
        except HTTPError as ex:
            raise RuntimeError(f"DuckDuckGo HTML search failed: HTTP {ex.code}") from ex
        except URLError as ex:
            raise RuntimeError(f"DuckDuckGo HTML search failed: {ex.reason}") from ex

        result_list = []
        for title_match in re.finditer(
            r"<a[^>]+class=\"[^\"]*result__a[^\"]*\"[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            following_html = html_text[title_match.end() : title_match.end() + 1600]
            snippet_match = re.search(
                r"class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</a>|"
                r"class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</div>",
                following_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            snippet_text = ""
            if snippet_match:
                snippet_text = snippet_match.group(1) or snippet_match.group(2) or ""
            result = WebSearchResult(
                title=self.clean_html(title_match.group(2)),
                url=self.normalize_duckduckgo_url(html.unescape(title_match.group(1))),
                snippet=self.clean_html(snippet_text),
            )
            if self.is_valid_result_url(result.url):
                result_list.append(result)
            if len(result_list) >= limit:
                break
        return self.dedupe_result_list(result_list)[:limit]

    def search_with_bing_api(self, query: str, limit: int) -> List[WebSearchResult]:
        endpoint = self.config.web_search_endpoint or "https://api.bing.microsoft.com/v7.0/search"
        url = f"{endpoint}?q={quote_plus(query)}&count={max(1, min(limit, 20))}&mkt=zh-CN"
        request = Request(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": self.config.web_search_api_key,
                "User-Agent": self.get_user_agent(),
            },
        )
        try:
            with self.open_request(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as ex:
            error_body = ex.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"Bing Search API failed: HTTP {ex.code} {error_body}") from ex
        except URLError as ex:
            raise RuntimeError(f"Bing Search API failed: {ex.reason}") from ex
        result_list = []
        for item in payload.get("webPages", {}).get("value", []):
            result = WebSearchResult(
                title=self.clean_text(item.get("name", "")),
                url=item.get("url", ""),
                snippet=self.clean_text(item.get("snippet", "")),
            )
            if self.is_valid_result_url(result.url):
                result_list.append(result)
            if len(result_list) >= limit:
                break
        return result_list

    def search_with_bing_rss(self, query: str, limit: int) -> List[WebSearchResult]:
        url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}&mkt=zh-CN"
        request = Request(
            url,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        try:
            with self.open_request(request) as response:
                xml_text = response.read().decode("utf-8", errors="ignore")
        except HTTPError as ex:
            raise RuntimeError(f"Bing RSS search failed: HTTP {ex.code}") from ex
        except URLError as ex:
            raise RuntimeError(f"Bing RSS search failed: {ex.reason}") from ex

        result_list = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as ex:
            raise RuntimeError(f"Bing RSS search failed: invalid XML {ex}") from ex
        for item in root.findall("./channel/item"):
            result = WebSearchResult(
                title=self.clean_text(item.findtext("title", "")),
                url=self.clean_text(item.findtext("link", "")),
                snippet=self.clean_html(item.findtext("description", "")),
            )
            if self.is_valid_result_url(result.url):
                result_list.append(result)
            if len(result_list) >= limit:
                break
        return self.dedupe_result_list(result_list)[:limit]

    def search_with_bing_html(self, query: str, limit: int) -> List[WebSearchResult]:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max(1, min(limit, 20))}&mkt=zh-CN"
        request = Request(
            url,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        try:
            with self.open_request(request) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
        except HTTPError as ex:
            raise RuntimeError(f"Bing HTML search failed: HTTP {ex.code}") from ex
        except URLError as ex:
            raise RuntimeError(f"Bing HTML search failed: {ex.reason}") from ex

        result_list = []
        block_list = re.findall(r"<li class=\"b_algo\".*?</li>", html_text, flags=re.IGNORECASE | re.DOTALL)
        for block in block_list:
            title_match = re.search(r"<h2[^>]*>.*?<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>.*?</h2>", block, flags=re.IGNORECASE | re.DOTALL)
            if not title_match:
                continue
            snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL)
            result = WebSearchResult(
                title=self.clean_html(title_match.group(2)),
                url=html.unescape(title_match.group(1)),
                snippet=self.clean_html(snippet_match.group(1) if snippet_match else ""),
            )
            if self.is_valid_result_url(result.url):
                result_list.append(result)
            if len(result_list) >= limit:
                break
        return self.dedupe_result_list(result_list)[:limit]

    def search_with_so_html(self, query: str, limit: int) -> List[WebSearchResult]:
        url = f"https://www.so.com/s?q={quote_plus(query)}"
        request = Request(
            url,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        try:
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            with opener.open(request, timeout=self.config.web_search_timeout_seconds) as response:
                html_text = response.read(256 * 1024).decode("utf-8", errors="ignore")
        except HTTPError as ex:
            raise RuntimeError(f"360 HTML search failed: HTTP {ex.code}") from ex
        except URLError as ex:
            raise RuntimeError(f"360 HTML search failed: {ex.reason}") from ex

        result_list = []
        block_list = re.findall(
            r"<li[^>]+class=\"[^\"]*res-list[^\"]*\".*?</li>",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not block_list:
            block_list = re.findall(r"<h3[^>]*class=\"[^\"]*res-title[^\"]*\".*?</h3>", html_text, flags=re.IGNORECASE | re.DOTALL)
        for block in block_list:
            title_match = re.search(r"<a[^>]+href=\"([^\"]+)\"([^>]*)>(.*?)</a>", block, flags=re.IGNORECASE | re.DOTALL)
            if not title_match:
                continue
            attr_text = title_match.group(2) or ""
            mdurl_match = re.search(r"data-mdurl=\"([^\"]+)\"", attr_text, flags=re.IGNORECASE)
            result_url = html.unescape(mdurl_match.group(1) if mdurl_match else title_match.group(1))
            snippet_match = re.search(r"class=\"[^\"]*res-desc[^\"]*\"[^>]*>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL)
            result = WebSearchResult(
                title=self.clean_html(title_match.group(3)),
                url=result_url,
                snippet=self.clean_html(snippet_match.group(1) if snippet_match else ""),
            )
            if self.is_valid_result_url(result.url):
                result_list.append(result)
            if len(result_list) >= limit:
                break
        return self.dedupe_result_list(result_list)[:limit]

    def search_with_sogou_html(self, query: str, limit: int) -> List[WebSearchResult]:
        url = f"https://www.sogou.com/web?query={quote_plus(query)}"
        request = Request(
            url,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                "Referer": "https://www.sogou.com/",
            },
        )
        try:
            with self.open_request(request) as response:
                html_text = response.read(350 * 1024).decode("utf-8", errors="ignore")
        except HTTPError as ex:
            raise RuntimeError(f"Sogou HTML search failed: HTTP {ex.code}") from ex
        except URLError as ex:
            raise RuntimeError(f"Sogou HTML search failed: {ex.reason}") from ex

        result_list = []
        block_list = re.findall(
            r"<div[^>]+class=\"[^\"]*vrwrap[^\"]*\".*?(?=<div[^>]+class=\"[^\"]*vrwrap[^\"]*\"|</body>)",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not block_list:
            block_list = [html_text]
        for block in block_list:
            title_match = re.search(
                r"<h3[^>]*>.*?<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>.*?</h3>",
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not title_match:
                continue
            result = WebSearchResult(
                title=self.clean_html(title_match.group(2)),
                url=self.normalize_sogou_url(html.unescape(title_match.group(1))),
                snippet=self.clean_html(block[title_match.end() : title_match.end() + 1800]),
            )
            if self.is_valid_result_url(result.url):
                result_list.append(result)
            if len(result_list) >= limit:
                break
        return self.dedupe_result_list(result_list)[:limit]

    def fetch_public_page_document(self, result: WebSearchResult) -> PublicPageDocument:
        if not self.is_valid_result_url(result.url):
            return PublicPageDocument(result.title, result.url, result.snippet, "")
        request = Request(
            result.url,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        try:
            with self.open_request(request) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text" not in content_type and "html" not in content_type and "json" not in content_type:
                    return PublicPageDocument(result.title, result.url, result.snippet, "")
                body = response.read(1024 * 1024)
                charset = self.extract_charset(content_type) or "utf-8"
                html_text = body.decode(charset, errors="ignore")
        except Exception as ex:
            logger.info("Public page fetch skipped, url=%s, error=%s", result.url, ex)
            return PublicPageDocument(result.title, result.url, result.snippet, "")
        page_title = self.extract_title(html_text) or result.title
        page_text = self.clean_html_document(html_text)
        return PublicPageDocument(page_title, result.url, result.snippet, page_text[:20000])

    def sleep_between_requests(self) -> None:
        if self.config.web_search_request_interval_seconds > 0:
            time.sleep(self.config.web_search_request_interval_seconds)

    def open_request(self, request: Request):
        return urlopen(
            request,
            timeout=self.config.web_search_timeout_seconds,
            context=self.build_ssl_context(),
        )

    def build_ssl_context(self):
        keylog_file = os.environ.pop("SSLKEYLOGFILE", None)
        try:
            context = ssl.create_default_context()
        finally:
            if keylog_file is not None:
                os.environ["SSLKEYLOGFILE"] = keylog_file
        if hasattr(context, "keylog_filename"):
            try:
                context.keylog_filename = None
            except Exception:
                pass
        return context

    def is_valid_result_url(self, url: str) -> bool:
        if not url or not url.startswith(("http://", "https://")):
            return False
        lower_url = url.lower()
        if any(lower_url.endswith(suffix) for suffix in BINARY_URL_SUFFIX_LIST):
            return False
        if any(token in lower_url for token in SKIP_HOST_TOKEN_LIST):
            return False
        host = urlparse(url).netloc.lower()
        return bool(host and "." in host)

    def normalize_duckduckgo_url(self, url: str) -> str:
        if url.startswith("//duckduckgo.com/l/"):
            url = f"https:{url}"
        parsed_url = urlparse(url)
        if parsed_url.netloc.endswith("duckduckgo.com") and parsed_url.path.startswith("/l/"):
            query_map = parse_qs(parsed_url.query)
            if query_map.get("uddg"):
                return query_map["uddg"][0]
        return url

    def normalize_sogou_url(self, url: str) -> str:
        clean_url = (url or "").strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        if clean_url.startswith("/"):
            return f"https://www.sogou.com{clean_url}"
        return clean_url

    def dedupe_result_list(self, result_list: List[WebSearchResult]) -> List[WebSearchResult]:
        dedupe_set = set()
        deduped_list = []
        for result in result_list:
            key = result.url.split("#")[0].rstrip("/")
            if key in dedupe_set:
                continue
            dedupe_set.add(key)
            deduped_list.append(result)
        return deduped_list

    def filter_relevant_result_list(self, query: str, result_list: List[WebSearchResult]) -> List[WebSearchResult]:
        token_list = self.build_query_relevance_token_list(query)
        if not token_list:
            return result_list
        filtered_list = []
        for result in result_list:
            haystack = " ".join([result.title, result.snippet, result.url]).upper()
            if any(token.upper() in haystack for token in token_list):
                filtered_list.append(result)
        return filtered_list

    def build_query_relevance_token_list(self, query: str) -> List[str]:
        cleaned_query = re.sub(r"site:\S+", " ", query or "", flags=re.IGNORECASE)
        token_list = re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9]{2,}", cleaned_query)
        generic_token_set = {
            "广东",
            "广州",
            "深圳",
            "东莞",
            "佛山",
            "中山",
            "珠海",
            "惠州",
            "公司",
            "企业",
            "企业名录",
            "名录",
            "电话",
            "联系电话",
            "联系人",
            "厂家",
            "工厂",
            "供应商",
            "供应链",
            "批发",
        }
        result_list = []
        for token in token_list:
            if token in generic_token_set or len(token) < 2:
                continue
            if token not in result_list:
                result_list.append(token)
        return result_list[:8]

    def clean_html_document(self, html_text: str) -> str:
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
        return self.clean_html(text)

    def clean_html(self, value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = html.unescape(text)
        return self.clean_text(text)

    def clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def extract_title(self, html_text: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html_text or "", flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return self.clean_html(match.group(1))[:200]

    def extract_charset(self, content_type: str) -> str:
        match = re.search(r"charset=([\w\-]+)", content_type or "", flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def get_user_agent(self) -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
