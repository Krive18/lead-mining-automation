# 1688 Category And Jitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store precise 1688 card categories in `product_name` and add randomized public-page pacing for 1688/Tianyancha collection.

**Architecture:** Keep the existing data model. Add a targeted 1688 card-category parser before the current product fallback, and centralize Playwright page wait jitter in small helper functions used by 1688 and enterprise public-web collectors.

**Tech Stack:** Python unittest, Playwright synchronous API, Vue frontend unchanged.

---

### Task 1: 1688 Card Category Product

**Files:**
- Modify: `backend/app/service/collector_service.py`
- Test: `backend/tests/test_alibaba_1688_collector.py`

- [ ] Write a failing test where a 1688 search card contains `工装、制服务Polo衫 男式卫衣` and `build_candidate()` returns that text as `product_name`.
- [ ] Run `python -m unittest tests.test_alibaba_1688_collector` and verify the test fails because the current product is the keyword fallback.
- [ ] Add a helper that extracts the card category from `parentText` and call it before the current `extract_product_name()` fallback.
- [ ] Run the same unittest and verify it passes.

### Task 2: Public Page Wait Jitter

**Files:**
- Modify: `backend/app/service/collector_service.py`
- Test: `backend/tests/test_alibaba_1688_collector.py`

- [ ] Write a failing test for a page-wait helper that converts a base wait into a jittered millisecond timeout.
- [ ] Run `python -m unittest tests.test_alibaba_1688_collector` and verify the helper is missing.
- [ ] Add `build_jittered_milliseconds()` and `wait_for_page_timeout_with_jitter()`.
- [ ] Replace fixed 1688 and enterprise public-web `page.wait_for_timeout(...)` page-settle waits with the helper.
- [ ] Run backend tests for 1688, enterprise address, Made-in-China, and existence verification.
