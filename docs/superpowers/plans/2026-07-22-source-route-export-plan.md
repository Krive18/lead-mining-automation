# 采集路线独立导出实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在线索库中按用户选择的采集路线单独导出线索，并让导出文件名清晰标识路线。

**Architecture:** 复用 `lead_record.source_type`、导出请求的 `source_group` 和后端 `SOURCE_GROUP_TYPE_MAP`。前端只增加独立导出筛选状态；后端增加请求白名单和路线文件名，不修改数据表。

**Tech Stack:** Vue 3、TypeScript、Pinia、FastAPI、Pydantic 2、openpyxl、pytest。

## Global Constraints

- “导出筛选”导出 A-D，“导出高价值”导出 A-B。
- 两类导出都叠加采集路线、行业、分配状态、城市和关键词条件。
- “当前模块”只使用当前线索模块，不受独立采集路线选择影响。
- 导出成功后继续将实际导出线索标记为已分配。
- 未知采集路线必须拒绝，不能退化成全部路线。

---

### Task 1: 导出路线契约与文件命名

**Files:**
- Modify: `backend/app/model/schema.py`
- Modify: `backend/app/service/export_service.py`
- Test: `backend/tests/test_export_service.py`

**Interfaces:**
- Consumes: `ExportCreateDTO.source_group` 和 `ExportCreateDTO.source_type`。
- Produces: 受白名单约束的 `source_group`；`ExportService.build_export_route_label(source_group, source_type) -> str`；带路线名称的 Excel 文件名。

- [ ] **Step 1: 添加失败测试**

增加测试验证 `source_group="alibaba_international"` 会传给仓储层、文件名包含“阿里国际站”，未知来源组触发 Pydantic 校验错误。

- [ ] **Step 2: 运行测试确认失败**

Run: `$env:PYTHONPATH='backend'; backend\.venv\Scripts\python.exe -m pytest backend/tests/test_export_service.py -q`

Expected: 新增的文件名或白名单断言失败。

- [ ] **Step 3: 实现最小后端改动**

将 `ExportCreateDTO.source_group` 改为包含现有来源组的 `Literal`；在 `ExportService` 中增加受控标签映射，并把标签传入 `build_unique_export_file_path`。

- [ ] **Step 4: 运行测试确认通过**

Run: `$env:PYTHONPATH='backend'; backend\.venv\Scripts\python.exe -m pytest backend/tests/test_export_service.py -q`

Expected: 全部通过。

### Task 2: 前端采集路线导出控件

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: 现有 `store.exportLead(levels, isPhoneMasked, filters)`。
- Produces: `exportSourceGroup` 和 `exportSourceGroupOptions`；“导出筛选”和“导出高价值”的完整筛选请求。

- [ ] **Step 1: 在顶部工具栏增加“采集路线”下拉框**

下拉值使用后端 `SOURCE_GROUP_TYPE_MAP` 已支持的组名；默认值为 `all`。

- [ ] **Step 2: 统一构建导出筛选参数**

新增前端辅助函数，将 `leadFilters` 的关键词和城市与顶部行业、分配状态、采集路线合并；清空可能残留的 `source_type`，确保所选 `source_group` 优先。

- [ ] **Step 3: 保持当前模块导出独立**

`exportCurrentModuleLead` 继续传递当前 `leadFilters.source_group`，不读取 `exportSourceGroup`。

- [ ] **Step 4: 调整工具栏样式并执行前端构建**

Run: `npm run build`

Workdir: `frontend`

Expected: `vue-tsc` 和 Vite 构建通过。

### Task 3: 全链路回归和运行验证

**Files:**
- Verify: `backend/tests`
- Verify: `frontend`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的最终实现。
- Produces: 可运行的前后端服务与健康检查结果。

- [ ] **Step 1: 运行后端全量测试**

Run: `$env:PYTHONPATH='backend'; backend\.venv\Scripts\python.exe -m pytest backend/tests -q`

Expected: 零失败。

- [ ] **Step 2: 重启项目**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File deployment\windows\start.ps1`

- [ ] **Step 3: 检查服务**

Run: `Invoke-RestMethod http://127.0.0.1:8000/api/health`

Expected: `status=ok`，同时 `127.0.0.1:5173` 保持监听。
