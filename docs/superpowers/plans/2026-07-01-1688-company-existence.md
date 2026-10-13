# 1688 Company Existence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing 1688 verifier use strict full-company-name evidence and export the requested audit fields.

**Architecture:** Keep the current FastAPI route and Vue page. Extend the focused backend service with a `search_keyword` field, stricter result metadata, and workbook headers; update the frontend type and table to display the new evidence fields.

**Tech Stack:** Python unittest, FastAPI service layer, openpyxl, Vue 3, TypeScript, Vite.

---

### Task 1: Backend Behavior Tests

**Files:**
- Create: `backend/tests/test_alibaba_1688_existence_service.py`
- Modify: `backend/app/service/alibaba_1688_existence_service.py`

- [ ] **Step 1: Write failing tests**

Cover exact matching, non-matching similar names, access-limit fallback, and workbook export headers.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest tests.test_alibaba_1688_existence_service -v` from `backend`.

Expected: fail because `search_keyword` and final export headers are not implemented yet.

- [ ] **Step 3: Implement minimal service changes**

Add `search_keyword` to `Alibaba1688ExistenceResult`, write it into summary items and Excel rows, and set it when each 1688 search URL is queried.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m unittest tests.test_alibaba_1688_existence_service -v` from `backend`.

Expected: all tests pass.

### Task 2: Frontend Evidence Columns

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/Alibaba1688ExistenceVerifier.vue`

- [ ] **Step 1: Add frontend fields**

Add `search_keyword` to the TypeScript result item and display `证据链接` plus `检索词` in the table.

- [ ] **Step 2: Build frontend**

Run: `npm --prefix frontend run build`

Expected: Vue type check and Vite build complete.

### Task 3: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run backend tests**

Run: `python -m unittest discover backend/tests -v` from project root.

Expected: all backend unit tests pass.

- [ ] **Step 2: Run frontend build**

Run: `npm --prefix frontend run build`

Expected: build passes.
