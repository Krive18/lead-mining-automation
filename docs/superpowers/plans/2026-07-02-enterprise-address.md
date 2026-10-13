# Enterprise Address Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture and expose enterprise addresses from Qixinbao/Tianyancha public pages.

**Architecture:** Reuse the existing `registered_address` field end to end. Improve only the public-web address parser, then expose the existing field in table and export surfaces.

**Tech Stack:** Python unittest backend, Vue 3 frontend, openpyxl export.

---

### Task 1: Public-Web Address Parser

**Files:**
- Modify: `backend/app/service/collector_service.py`
- Test: `backend/tests/test_enterprise_public_web_address.py`

- [ ] Write failing tests for `EnterprisePublicWebCollector.extract_registered_address` with `企业地址`, `联系地址`, and `通讯地址`.
- [ ] Run `python -m unittest backend.tests.test_enterprise_public_web_address` and verify the new tests fail because unsupported labels return empty or noisy values.
- [ ] Add only address label parsing and cleanup logic.
- [ ] Run the same unittest and verify it passes.

### Task 2: Address Visibility

**Files:**
- Modify: `frontend/src/components/LeadTable.vue`
- Modify: `backend/app/service/export_service.py`

- [ ] Add the existing `registered_address` field to the lead table.
- [ ] Add the existing `registered_address` field to `EXPORT_HEADER`.
- [ ] Run frontend build.
- [ ] Run backend tests covering address parsing and existing Made-in-China enrichment.
