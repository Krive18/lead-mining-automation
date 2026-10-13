# 1688 Existence Realtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert 1688 enterprise counter-verification from a blocking Excel request into a visible, pollable job that marks a company as existing when the search results page contains any 1688 link.

**Architecture:** Keep Excel parsing and export generation in `Alibaba1688ExistenceService`, add an in-memory job registry with progress snapshots, and expose a POST-start plus GET-status API. The frontend starts a job, polls its status, and renders the running company, counts, partial results, and final download links.

**Tech Stack:** FastAPI background tasks, Python dataclasses/thread locks, OpenPyXL, Vue 3 Composition API, existing fetch client.

---

### Task 1: Backend Rules And Job State

**Files:**
- Modify: `backend/tests/test_alibaba_1688_existence_service.py`
- Modify: `backend/app/service/alibaba_1688_existence_service.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove an arbitrary 1688 result means “存在”, and that job creation returns a progress snapshot before processing finishes.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_alibaba_1688_existence_service -v`

- [ ] **Step 3: Implement minimal backend service changes**

Add `Alibaba1688ExistenceJob`, `create_verification_job`, `run_verification_job`, `get_verification_job_snapshot`, and make `judge_public_search_index_result` mark “存在” on the first 1688 URL.

- [ ] **Step 4: Run backend tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_alibaba_1688_existence_service -v`

### Task 2: API Endpoints

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/model/schema.py`

- [ ] **Step 1: Add job response schema fields**

Expose `job_id`, `status`, `processed_count`, `current_company_name`, `current_search_keyword`, `error_message`, and existing summary/export fields.

- [ ] **Step 2: Change POST endpoint to start a background task**

`POST /api/1688-existence-verifications` should return immediately with a job snapshot and schedule `run_verification_job`.

- [ ] **Step 3: Add status endpoint**

`GET /api/1688-existence-verifications/{job_id}` should return the latest snapshot.

### Task 3: Frontend Polling UI

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/Alibaba1688ExistenceVerifier.vue`

- [ ] **Step 1: Add job fields to TypeScript types**

Add job/progress fields while preserving download/result fields.

- [ ] **Step 2: Add polling client**

Add `getAlibaba1688ExistenceVerification(jobId)`.

- [ ] **Step 3: Update component flow**

After submit, render immediate status, poll every 1.5 seconds while status is `pending` or `running`, display current company/search keyword/progress, and stop polling on completion/failure.

### Task 4: Verification And Restart

**Files:**
- No code files.

- [ ] **Step 1: Run backend tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_alibaba_1688_existence_service -v`

- [ ] **Step 2: Run frontend build**

Run: `npm run build`

- [ ] **Step 3: Restart project**

Run: `powershell.exe -ExecutionPolicy Bypass -File deployment/windows/start.ps1`

- [ ] **Step 4: Verify health**

Check `http://127.0.0.1:8000/api/health` and `http://127.0.0.1:5173/`.
