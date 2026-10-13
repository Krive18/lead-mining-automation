# Alibaba International Guangdong Supplier Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Alibaba.com supplier-list collector that searches user product keywords, saves only confirmed Guangdong suppliers, and persists English company name, main product subcategories, raw platform shop level, and supplier profile URL without calling Qixin.

**Architecture:** Add a dedicated `alibaba_international` source and a focused `AlibabaInternationalSupplierCollector` rather than reusing 1688-specific Chinese parsing. Extend the lead field chain with `company_name_en` and `shop_level`, then wire the new source through task creation, persistence, listing, export, and the existing Vue task center. The collector uses a visible persistent Playwright profile, reads supplier cards only, and applies deterministic Guangdong, keyword relevance, badge, and deduplication rules before returning `CollectedLeadDTO` values.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Playwright sync API, SQLite/MySQL migration helpers, openpyxl, Vue 3, TypeScript, Vite, pytest/unittest.

## Global Constraints

- Source type is exactly `alibaba_international`.
- Search user product keywords unchanged; never append `factory` or `manufacturer`.
- Read Alibaba.com supplier-list cards only; do not open supplier detail pages.
- Save only cards with explicit Guangdong province or Guangdong city evidence.
- Save raw official platform badge text; do not translate or infer a Chinese level.
- Do not call Qixin during collection.
- Missing shop level is allowed; missing English company name, Guangdong evidence, or main product category rejects the card.
- Persist `company_name_en` and `shop_level` through database, API, frontend, and Excel export.
- Preserve already saved leads if a later page fails.
- This workspace is not a Git repository; replace commit steps with recorded test/build checkpoints.

---

### Task 1: Source Contract And Complete Field Chain

**Files:**
- Create: `backend/tests/test_alibaba_international_field_chain.py`
- Modify: `backend/app/core/constant.py`
- Modify: `backend/app/model/schema.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/repository/lead_repository.py`
- Modify: `backend/app/service/export_service.py`
- Modify: `frontend/src/types.ts`

**Interfaces:**
- Produces: `SOURCE_TYPE_ALIBABA_INTERNATIONAL = "alibaba_international"`.
- Produces: `CollectedLeadDTO.company_name_en: str` and `CollectedLeadDTO.shop_level: str`.
- Produces: lead API fields `company_name_en` and `shop_level`.
- Produces: Excel columns `英文公司名称` and `店铺等级`.

- [ ] **Step 1: Write failing source and persistence tests**

Create tests that instantiate both Pydantic DTOs with `alibaba_international`, initialize a temporary SQLite database, insert one lead, read it back, and assert both new fields survive:

```python
request = TaskCreateDTO(
    source_type="alibaba_international",
    industry="其他",
    keywords=["game controller"],
    collect_limit=5,
    is_qcc_enabled=False,
    qcc_limit=0,
)
lead = CollectedLeadDTO(
    source_type="alibaba_international",
    source_keyword="game controller",
    industry="其他",
    suspected_company_name="Shenzhen Example Technology Co., Ltd.",
    company_name_en="Shenzhen Example Technology Co., Ltd.",
    product_name="Game Controllers; Gamepads",
    shop_level="Verified Supplier; Custom Manufacturer",
)
assert request.source_type == "alibaba_international"
assert lead.company_name_en == "Shenzhen Example Technology Co., Ltd."
assert lead.shop_level == "Verified Supplier; Custom Manufacturer"
```

Use the temporary-database pattern from `backend/tests/test_credit_code_field_chain.py` and assert `LeadRepository.get_lead_by_id()` returns the same values.

- [ ] **Step 2: Write failing export header test**

```python
from app.service.export_service import EXPORT_HEADER

header_map = dict(EXPORT_HEADER)
assert header_map["company_name_en"] == "英文公司名称"
assert header_map["shop_level"] == "店铺等级"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_alibaba_international_field_chain.py -q
```

Expected: failures because the source literal and fields do not exist.

- [ ] **Step 4: Implement source constant and DTO fields**

Add the constant, add the source literal to `TaskCreateDTO` and `CollectedLeadDTO`, and add defaults:

```python
company_name_en: str = ""
shop_level: str = ""
```

- [ ] **Step 5: Implement SQLite and MySQL schema/migration columns**

Add columns to both create-table schemas and `migrate_schema()`:

```sql
company_name_en TEXT NOT NULL DEFAULT '',
shop_level TEXT NOT NULL DEFAULT ''
```

Use `VARCHAR(255)` for MySQL. Add idempotent `column_exists()` migration checks for existing databases.

- [ ] **Step 6: Implement repository and export propagation**

Add the fields to `LeadRepository.insert_lead()` SQL columns, placeholders, and values. Ensure read/list queries continue using `SELECT *` or explicitly include both fields. Insert export headers immediately after company name and product name respectively.

- [ ] **Step 7: Run focused tests and checkpoint**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_alibaba_international_field_chain.py tests/test_export_service.py -q
```

Expected: all focused tests pass.

---

### Task 2: Deterministic Supplier Card Parser

**Files:**
- Create: `backend/app/service/alibaba_international_collector.py`
- Create: `backend/tests/test_alibaba_international_collector.py`

**Interfaces:**
- Produces: `AlibabaInternationalCandidate` dataclass with `source_keyword`, `company_name_en`, `product_name`, `shop_level`, `location_text`, and `profile_url`.
- Produces: `AlibabaInternationalSupplierCollector.build_candidate(keyword: str, raw_item: dict, industry: str) -> Optional[AlibabaInternationalCandidate]`.
- Produces: `AlibabaInternationalSupplierCollector.is_guangdong_location(text: str) -> bool`.

- [ ] **Step 1: Write failing parser tests for a valid Guangdong card**

```python
raw_item = {
    "companyName": "Shenzhen Cico Technology Co., Ltd.",
    "locationText": "Guangdong, China",
    "mainProducts": ["Game Controllers", "Gamepads", "Mobile Gaming Accessories"],
    "badgeTextList": ["Verified Supplier", "Custom Manufacturer", "Trade Assurance"],
    "profileUrl": "https://example.en.alibaba.com/",
    "cardText": "Game Controllers Gamepads",
}
candidate = collector.build_candidate("game controller", raw_item, "其他")
assert candidate.company_name_en == "Shenzhen Cico Technology Co., Ltd."
assert candidate.product_name == "Game Controllers; Gamepads; Mobile Gaming Accessories"
assert candidate.shop_level == "Verified Supplier; Custom Manufacturer"
```

Assert `Trade Assurance`, response rate, years, and services are excluded from `shop_level`.

- [ ] **Step 2: Write failing rejection and dedupe tests**

Cover Zhejiang rejection, `China`-only rejection, missing products rejection, unrelated product rejection, empty badge acceptance, and normalized English company-name/profile URL deduplication.

- [ ] **Step 3: Run parser tests and verify RED**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_alibaba_international_collector.py -q
```

Expected: import failure because the collector module does not exist.

- [ ] **Step 4: Implement minimal parser**

Use explicit constants:

```python
SHOP_LEVEL_BADGE_SET = {
    "Verified Supplier",
    "Gold Supplier",
    "Custom Manufacturer",
    "Multispecialty Supplier",
}
GUANGDONG_LOCATION_TOKEN_SET = {
    "guangdong", "guangzhou", "shenzhen", "dongguan", "foshan",
    "zhuhai", "zhongshan", "huizhou", "jiangmen", "shantou",
    "jieyang", "qingyuan", "zhaoqing", "chaozhou",
}
```

Normalize whitespace and punctuation for matching, preserve original visible text for stored company/products/badges, and never substitute the search keyword for missing products.

- [ ] **Step 5: Run focused parser tests**

Run the Task 2 test command. Expected: all tests pass.

---

### Task 3: Browser Collection Workflow And Diagnostics

**Files:**
- Modify: `backend/app/service/alibaba_international_collector.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_alibaba_international_collector.py`

**Interfaces:**
- Produces: `collect(industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]`.
- Produces: `build_search_url(keyword: str, page_number: int) -> str` targeting Alibaba.com supplier results.
- Produces diagnostic attributes compatible with `TaskService.insert_after_collect_event()` or a dedicated `last_collect_diagnostic` string.

- [ ] **Step 1: Write failing URL and result-conversion tests**

Assert that `build_search_url("game controller", 1)` contains the unchanged encoded keyword and a supplier-search route, and does not contain `factory` or `manufacturer`. Assert candidate conversion returns:

```python
CollectedLeadDTO(
    source_type="alibaba_international",
    source_keyword="game controller",
    industry="其他",
    suspected_company_name="Shenzhen Cico Technology Co., Ltd.",
    company_name_en="Shenzhen Cico Technology Co., Ltd.",
    product_name="Game Controllers; Gamepads",
    shop_level="Verified Supplier; Custom Manufacturer",
    region_text="Guangdong, China",
    province="广东",
    shop_url="https://example.en.alibaba.com/",
    profile_url="https://example.en.alibaba.com/",
)
```

If `CollectedLeadDTO` does not expose province directly, assert `region_text` carries verified Guangdong evidence and let repository region preparation persist province/city.

- [ ] **Step 2: Write failing incremental-preservation test**

Stub page 1 with one valid card and page 2 with a controlled exception. Assert `collect()` returns or has already yielded/saved the first card through the task processing boundary rather than discarding it. If collector return semantics cannot preserve data mid-run, change collection to stop further paging after an error while returning accumulated candidates.

- [ ] **Step 3: Run focused tests and verify RED**

Run Task 2 tests and confirm the new browser workflow assertions fail.

- [ ] **Step 4: Add dedicated configuration**

Add `AppConfig` fields and environment defaults:

```text
ALIBABA_INTERNATIONAL_HEADLESS=false
ALIBABA_INTERNATIONAL_BROWSER_CHANNEL=msedge
ALIBABA_INTERNATIONAL_PAGE_TIMEOUT_MS=25000
ALIBABA_INTERNATIONAL_REQUEST_INTERVAL_SECONDS=5
ALIBABA_INTERNATIONAL_MANUAL_VERIFY_ENABLED=true
ALIBABA_INTERNATIONAL_USER_DATA_DIR=backend/data/browser-profile/alibaba-international
```

Create the profile directory in `get_config()` and never reuse the 1688 profile.

- [ ] **Step 5: Implement Playwright supplier-list extraction**

Launch a persistent visible context. Navigate one keyword/page at a time, wait for DOM content, perform bounded scrolling, and evaluate only visible supplier cards. Return structured raw items with exact fields expected by `build_candidate()`. Do not click supplier cards or product links.

- [ ] **Step 6: Implement access-limit detection and diagnostics**

Detect login, CAPTCHA, access-denied, and empty-result surfaces from title/URL/visible text. Set diagnostics such as:

```text
Alibaba国际站未采集到线索：解析卡片 18 个，广东通过 7 个，关键词相关 0 个；实际搜索词：game controller。
```

Close browser/context in `finally`, but return accumulated results after a later-page non-auth parsing failure.

- [ ] **Step 7: Run focused tests**

Run `test_alibaba_international_collector.py`. Expected: all parser, URL, filtering, and preservation tests pass.

---

### Task 4: Task Service And Source Routing

**Files:**
- Create: `backend/tests/test_alibaba_international_task.py`
- Modify: `backend/app/service/collector_service.py`
- Modify: `backend/app/service/task_service.py`
- Modify: `backend/app/repository/lead_repository.py`
- Modify: `backend/app/service/export_service.py`

**Interfaces:**
- Consumes: `AlibabaInternationalSupplierCollector.collect()` from Task 3.
- Produces: source group key `alibaba_international`.
- Produces: task name `阿里国际站 其他 供应商采集` (industry varies).

- [ ] **Step 1: Write failing routing tests**

Assert:

```python
collector = CollectorFactory().get_collector("alibaba_international")
assert isinstance(collector, AlibabaInternationalSupplierCollector)
assert "alibaba_international" in PUBLIC_WEB_ONLY_SOURCE_TYPE_SET
assert "alibaba_international" not in PHONE_REQUIRED_SOURCE_TYPE_SET
assert SOURCE_GROUP_TYPE_MAP["alibaba_international"] == ("alibaba_international",)
assert service.build_task_name("alibaba_international", "其他") == "阿里国际站 其他 供应商采集"
```

- [ ] **Step 2: Write failing no-Qixin/no-QCC test**

Create a task request with `is_qcc_enabled=True`, call task creation, and assert public-page normalization stores `is_qcc_enabled=0` and `qcc_limit=0`. Stub the collector and assert no Qixin API service method is called during `run_task()`.

- [ ] **Step 3: Run routing tests and verify RED**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_alibaba_international_task.py -q
```

- [ ] **Step 4: Wire collector factory, task sets, source group, and task name**

Use a local import in `CollectorFactory.get_collector()` to avoid coupling the focused collector module to the existing 8,000-line collector module:

```python
if source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
    from app.service.alibaba_international_collector import AlibabaInternationalSupplierCollector
    return AlibabaInternationalSupplierCollector()
```

Add the source to `PUBLIC_WEB_ONLY_SOURCE_TYPE_SET`, explicitly exclude it from phone-required cleanup, and add a task-start event explaining that collection uses supplier-list cards and does not call Qixin.

- [ ] **Step 5: Ensure Guangdong acceptance uses collector evidence**

Update `TaskService.is_guangdong_lead()` so Alibaba International leads pass only when the collector supplied verified `region_text`/province evidence. Do not infer Guangdong from an English company-name prefix alone.

- [ ] **Step 6: Run focused task tests**

Run Task 4 tests and relevant existing source tests. Expected: all pass.

---

### Task 5: Task Center, Lead Library, And Export Presentation

**Files:**
- Modify: `frontend/src/components/TaskComposer.vue`
- Modify: `frontend/src/components/LeadTable.vue`
- Modify: `frontend/src/utils/format.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css` only if current table styles cannot fit the two fields.

**Interfaces:**
- Consumes: `LeadRecord.company_name_en` and `LeadRecord.shop_level`.
- Produces: task-center option `阿里国际站采集` with value `alibaba_international`.
- Produces: lead source tab `阿里国际站` with group `alibaba_international`.

- [ ] **Step 1: Add frontend contract fields and source label**

Extend `LeadRecord`, add the source to `formatSourceType()`, and add the source group tab.

- [ ] **Step 2: Add task-center source option and copy**

Add:

```ts
{ value: 'alibaba_international', label: '阿里国际站采集' }
```

Treat it as a public-page source so QCC controls remain disabled. Show the guide:

```text
按产品关键词采集阿里国际站广东供应商列表页，仅保存英文公司名、主营小类目和平台店铺等级，不自动调用启信宝。
```

For this source, example keyword placeholder is `stage light,game controller,garment steamer`. Do not overwrite a user-entered keyword when switching back and forth.

- [ ] **Step 3: Present the requested fields without making the table wider than necessary**

In the existing company cell, prefer `company_name_en` for Alibaba International and keep other source rendering unchanged. Add a compact `店铺等级` column adjacent to product, with `-` when empty. Update empty-row `colspan`.

- [ ] **Step 4: Run frontend typecheck and production build**

```powershell
cd frontend
npm.cmd run build
```

Expected: `vue-tsc --noEmit` and Vite build complete with exit code 0.

---

### Task 6: Full Verification And Local Browser Check

**Files:**
- Verify only; fix only defects directly caused by Tasks 1-5.

**Interfaces:**
- Verifies the complete feature contract.

- [ ] **Step 1: Run all backend source tests**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: zero failures.

- [ ] **Step 2: Run frontend build after all code changes**

```powershell
cd frontend
npm.cmd run build
```

Expected: zero TypeScript/build errors.

- [ ] **Step 3: Restart local project and verify health**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deployment\windows\start.ps1
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Expected backend response: `{"status":"ok"}` and ports 8000/5173 listening.

- [ ] **Step 4: Verify task-center UI in a real browser**

Check desktop and narrow viewport:

- `阿里国际站采集` is visible and selectable.
- Keyword and quantity controls do not shift or overlap.
- QCC controls are disabled for this source.
- Guide text says Guangdong supplier-list collection and no automatic Qixin call.
- Existing source options still work.

- [ ] **Step 5: Run one bounded live collection smoke test**

Use one product keyword and a limit of 1. Confirm the browser stays on supplier-list pages and does not navigate into a supplier detail page. Inspect task logs and the saved lead:

- source type is `alibaba_international`;
- English company name is non-empty;
- product subcategory is non-empty and not the search keyword fallback;
- shop level is raw badge text or empty;
- province is Guangdong;
- profile URL is Alibaba.com;
- no Qixin enrichment task or Qixin usage event is created.

If Alibaba.com presents login/CAPTCHA, stop the smoke test at the supported manual verification state; do not bypass it.

- [ ] **Step 6: Verify Excel export**

Export the smoke-test lead and assert the workbook contains `英文公司名称`, `产品/主营`, `店铺等级`, and a supplier-profile URL under `来源主页`.

- [ ] **Step 7: Record final evidence**

Report backend test count, frontend build result, local URLs, live smoke-test outcome, and any external login/CAPTCHA limitation. Do not claim collection success unless the live card and stored database row were observed.
