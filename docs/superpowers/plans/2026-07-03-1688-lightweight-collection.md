# 1688 Lightweight Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 1688 collection default to low-risk list-page extraction while preserving accurate small product categories.

**Architecture:** The 1688 collector will parse search-result cards into candidates, convert candidates directly into leads without opening 1688 detail pages, and keep a disabled-by-default detail fallback for missing product categories. Tianyancha enrichment will still fill company fields, but it will not overwrite valid 1688 list-card product values.

**Tech Stack:** Python 3, FastAPI backend, Playwright collector, unittest/pytest test suite, MySQL persistence.

---

### Task 1: Lock Product Subcategory Behavior With Tests

**Files:**
- Modify: `backend/tests/test_alibaba_1688_collector.py`

- [ ] **Step 1: Write failing tests for 2-3 product tokens joined by `、`**

Change current product expectations so list-card examples assert values such as:

```python
self.assertEqual(candidate.product_name, "工装、制服务Polo衫、男式卫衣")
self.assertEqual(candidate.product_name, "女士家居服、童家居服套装、睡袍")
self.assertEqual(candidate.product_name, "女士家居服、睡裙、情侣家居服")
self.assertEqual(candidate.product_name, "连衣裙、女式T恤、大码连衣裙")
```

- [ ] **Step 2: Add test for exact user screenshot examples**

Add:

```python
def test_extract_card_category_keeps_first_three_small_categories(self):
    collector = Alibaba1688PublicPageCollector()
    product = collector.extract_search_card_category_product_name(
        "东莞市虎门亦博服饰 东莞 诚2年 | 连衣裙 女式T恤 大码连衣裙 | 96%响应率 | 100%履约率",
        "东莞市虎门亦博服饰",
    )
    self.assertEqual(product, "连衣裙、女式T恤、大码连衣裙")
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py -q
```

Expected: FAIL because current extractor returns space-separated strings or keeps too much text.

### Task 2: Implement Product Subcategory Extractor

**Files:**
- Modify: `backend/app/service/collector_service.py`

- [ ] **Step 1: Add small-category tokenization helpers**

Add helper methods near `extract_search_card_category_product_name`:

```python
def split_1688_card_category_tokens(self, value: str) -> List[str]:
    normalized_value = re.sub(r"[、,，/|]+", " ", self.clean_text(value))
    return [token.strip() for token in normalized_value.split() if token.strip()]

def normalize_1688_card_category_product(self, value: str, company_name: str = "") -> str:
    token_list = []
    for token in self.split_1688_card_category_tokens(value):
        clean_token = self.clean_1688_card_category_segment(token, company_name)
        if self.is_1688_card_category_segment(clean_token):
            append_unique_text(token_list, clean_token)
        if len(token_list) >= 3:
            break
    return "、".join(token_list)
```

- [ ] **Step 2: Route all card category extraction through normalizer**

Update `extract_search_card_category_product_name` so both marked and fallback paths return `normalize_1688_card_category_product(...)`.

- [ ] **Step 3: Run focused tests**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py -q
```

Expected: PASS for product extraction tests.

### Task 3: Add City Priority and Detail Fallback Config

**Files:**
- Modify: `backend/app/service/collector_service.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: Write failing city-priority test**

Add to `backend/tests/test_alibaba_1688_collector.py`:

```python
def test_build_search_keyword_list_prioritizes_target_guangdong_cities(self):
    collector = Alibaba1688PublicPageCollector()
    keyword_list = collector.build_search_keyword_list("服装", ["服装工厂"])
    self.assertEqual(keyword_list[:4], ["广州服装工厂", "清远服装工厂", "佛山服装工厂", "东莞服装工厂"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py::Alibaba1688CollectorTest::test_build_search_keyword_list_prioritizes_target_guangdong_cities -q
```

Expected: FAIL because Qingyuan is not currently in the priority list.

- [ ] **Step 3: Update priority constants and config**

Set:

```python
PRIORITY_GUANGDONG_CITY_LIST = ["广州", "清远", "佛山", "东莞"]
```

Add config field:

```python
alibaba_1688_detail_fallback_enabled: bool
alibaba_1688_detail_fallback_limit: int
```

Default values:

```python
alibaba_1688_detail_fallback_enabled=parse_bool(os.getenv("ALIBABA_1688_DETAIL_FALLBACK_ENABLED"), False)
alibaba_1688_detail_fallback_limit=parse_int(os.getenv("ALIBABA_1688_DETAIL_FALLBACK_LIMIT"), 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py::Alibaba1688CollectorTest::test_build_search_keyword_list_prioritizes_target_guangdong_cities -q
```

Expected: PASS.

### Task 4: Make 1688 Default To List-Page-Only Leads

**Files:**
- Modify: `backend/app/service/collector_service.py`
- Modify: `backend/tests/test_alibaba_1688_collector.py`

- [ ] **Step 1: Write failing default-no-detail test**

Add:

```python
def test_collect_candidate_to_lead_does_not_open_detail_by_default(self):
    collector = Alibaba1688PublicPageCollector()
    candidate = AlibabaCandidate(
        source_keyword="广州服装工厂",
        company_name="广州市玉鹏服装有限公司",
        product_name="连衣裙、女式T恤、大码连衣裙",
        shop_url="https://example.1688.com/",
        profile_url="https://example.1688.com/",
        raw_text="广州市玉鹏服装有限公司 广州 超级工厂 连衣裙 女式T恤 大码连衣裙",
    )
    collector.enrich_candidate = Mock(side_effect=AssertionError("detail should not be opened"))
    lead = collector.collect_search_candidate_to_lead(Mock(), candidate, "服装", 0)
    self.assertEqual(lead.suspected_company_name, "广州市玉鹏服装有限公司")
    self.assertEqual(lead.product_name, "连衣裙、女式T恤、大码连衣裙")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py::Alibaba1688CollectorTest::test_collect_candidate_to_lead_does_not_open_detail_by_default -q
```

Expected: FAIL because `collect_search_candidate_to_lead` does not exist.

- [ ] **Step 3: Implement lead conversion helper and use it in collect loop**

Add:

```python
def should_use_detail_fallback(self, candidate: AlibabaCandidate, detail_fallback_count: int) -> bool:
    if not self.config.alibaba_1688_detail_fallback_enabled:
        return False
    if candidate.product_name:
        return False
    return detail_fallback_count < max(0, self.config.alibaba_1688_detail_fallback_limit)

def collect_search_candidate_to_lead(self, page, candidate: AlibabaCandidate, industry: str, detail_fallback_count: int) -> Optional[CollectedLeadDTO]:
    if self.should_use_detail_fallback(candidate, detail_fallback_count):
        return self.enrich_candidate(page, candidate, industry)
    return self.build_fallback_lead_from_search_candidate(candidate, industry)
```

Update the main `collect` loop to call this helper and increment detail checked counters only when the helper uses fallback.

- [ ] **Step 4: Run focused test**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py::Alibaba1688CollectorTest::test_collect_candidate_to_lead_does_not_open_detail_by_default -q
```

Expected: PASS.

### Task 5: Preserve 1688 Product During Tianyancha Enrichment

**Files:**
- Modify: `backend/app/service/collector_service.py`
- Modify: `backend/tests/test_alibaba_1688_collector.py`

- [ ] **Step 1: Write failing merge test**

Add:

```python
def test_tianyancha_enrichment_does_not_overwrite_1688_product(self):
    collector = Alibaba1688TianyanchaCollector()
    target = CollectedLeadDTO(
        source_type="alibaba_1688",
        source_keyword="广州服装工厂",
        industry="服装",
        suspected_company_name="广州市玉鹏服装有限公司",
        product_name="连衣裙、女式T恤、大码连衣裙",
    )
    source = CollectedLeadDTO(
        source_type="tianyancha_public_web",
        source_keyword="广州市玉鹏服装有限公司",
        industry="服装",
        suspected_company_name="广州市玉鹏服装有限公司",
        product_name="服装产品",
        phone="13800138000",
    )
    collector.merge_enrichment(target, source)
    self.assertEqual(target.product_name, "连衣裙、女式T恤、大码连衣裙")
```

- [ ] **Step 2: Run test to verify it fails if current merge overwrites product**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py::Alibaba1688CollectorTest::test_tianyancha_enrichment_does_not_overwrite_1688_product -q
```

Expected: FAIL if merge overwrites the product field.

- [ ] **Step 3: Update merge behavior**

In `Alibaba1688TianyanchaCollector.merge_enrichment`, only assign `target.product_name = source.product_name` when `target.product_name` is empty or a non-product label.

- [ ] **Step 4: Run focused test**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_alibaba_1688_collector.py::Alibaba1688CollectorTest::test_tianyancha_enrichment_does_not_overwrite_1688_product -q
```

Expected: PASS.

### Task 6: Full Verification

**Files:**
- Verify backend and frontend only.

- [ ] **Step 1: Run backend tests**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm run build
```

Working directory: `frontend`

Expected: Vue TypeScript check and Vite build pass.

- [ ] **Step 3: Restart project**

Run backend and frontend, then verify:

```powershell
curl.exe -s -S http://127.0.0.1:8000/api/health
curl.exe -s -S -I http://127.0.0.1:5173/
```

Expected: backend returns `{"status":"ok"}` and frontend returns HTTP 200.

- [ ] **Step 4: Commit**

This workspace is not a git repository, so no commit command can be run. Record the changed files in the final response.
