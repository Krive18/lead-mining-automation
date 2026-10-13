# 中国制造网 + 天眼查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fully automated `中国制造网 + 天眼查` lead collection path and remove `企查查` / `爱企查` from the task creation choices.

**Architecture:** Add a new `made_in_china_tianyancha` source type. A focused China Made collector extracts public company-name candidates from 中国制造网 company search results with 华南 filtering, then a combination collector reuses the existing Tianyancha `collect_by_company_names` flow for legal person, phone, scope, and address enrichment.

**Tech Stack:** Python 3.9, FastAPI, Pydantic v2, Playwright sync API, MySQL/SQLite repository layer, Vue 3, TypeScript, Vite.

---

## File Structure

- Modify `backend/app/core/constant.py`
  - Add the new source type constant.
- Modify `backend/app/model/schema.py`
  - Allow the new source type in `TaskCreateDTO` and `CollectedLeadDTO`.
- Modify `backend/app/service/task_service.py`
  - Treat the new source as public-web only, build the task name, add profile-busy checks, add a China Made pre-login warmup, and add empty-result diagnostics.
- Modify `backend/app/api/routes.py`
  - Add `POST /api/browser-warmup/made-in-china`.
- Modify `backend/app/service/collector_service.py`
  - Add China Made constants, candidate dataclass, public-page collector, combination collector, and factory wiring.
- Modify `backend/app/repository/lead_repository.py`
  - Add a source-group filter for China Made leads.
- Modify `backend/app/service/export_service.py`
  - Treat China Made + Tianyancha phone source as Tianyancha in exports.
- Create `backend/tests/test_made_in_china_source_type.py`
  - Fast source-type and service plumbing tests.
- Create `backend/tests/test_made_in_china_collector.py`
  - Pure parser and combination collector tests without real network access.
- Modify `frontend/src/components/TaskComposer.vue`
  - Remove `企查查` and `爱企查` from visible task choices; add `中国制造网 + 天眼查` and its pre-login button.
- Modify `frontend/src/api/client.ts`
  - Add `warmupMadeInChinaBrowser`.
- Modify `frontend/src/utils/format.ts`
  - Add display text for the new source.
- Modify `frontend/src/components/LeadTable.vue`
  - Add a source-group tab for China Made leads; remove visible `企查查` / `爱企查` tabs.
- Modify `frontend/src/App.vue`
  - Update topbar description to match visible collection choices.

## Task 1: Source Type Plumbing

**Files:**
- Create: `backend/tests/test_made_in_china_source_type.py`
- Modify: `backend/app/core/constant.py`
- Modify: `backend/app/model/schema.py`
- Modify: `backend/app/service/task_service.py`
- Modify: `backend/app/util/browser_warmup_runner.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/repository/lead_repository.py`
- Modify: `backend/app/service/export_service.py`

- [ ] **Step 1: Write failing backend source-type tests**

Create `backend/tests/test_made_in_china_source_type.py`:

```python
import unittest

from app.core.constant import SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA
from app.model.schema import CollectedLeadDTO, TaskCreateDTO
from app.repository.lead_repository import SOURCE_GROUP_TYPE_MAP
from app.service.export_service import TIANYANCHA_EXPORT_SOURCE_TYPE_SET
from app.service.task_service import PHONE_REQUIRED_SOURCE_TYPE_SET, PUBLIC_WEB_ONLY_SOURCE_TYPE_SET, TaskService


class MadeInChinaSourceTypeTest(unittest.TestCase):
    def test_task_create_accepts_made_in_china_source_type(self):
        request = TaskCreateDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            industry="3C数码",
            keywords=["手机壳工厂"],
            collect_limit=5,
            is_qcc_enabled=False,
            qcc_limit=0,
        )

        self.assertEqual(request.source_type, "made_in_china_tianyancha")

    def test_collected_lead_accepts_made_in_china_source_type(self):
        lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword="手机壳工厂",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
        )

        self.assertEqual(lead.source_type, SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)

    def test_task_service_treats_made_in_china_as_public_web_source(self):
        service = TaskService.__new__(TaskService)

        self.assertIn(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, PUBLIC_WEB_ONLY_SOURCE_TYPE_SET)
        self.assertIn(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, PHONE_REQUIRED_SOURCE_TYPE_SET)
        self.assertEqual(
            service.build_task_name(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, "3C数码"),
            "中国制造网+天眼查 3C数码 线索采集",
        )

    def test_repository_and_export_source_groups_include_made_in_china(self):
        self.assertEqual(
            SOURCE_GROUP_TYPE_MAP["made_in_china"],
            (SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,),
        )
        self.assertIn(SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA, TIANYANCHA_EXPORT_SOURCE_TYPE_SET)

    def test_task_service_exposes_made_in_china_warmup(self):
        service = TaskService.__new__(TaskService)

        self.assertTrue(callable(getattr(service, "start_made_in_china_warmup")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_source_type -v
```

Expected: FAIL with `ImportError` or Pydantic validation error because `SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA` is not defined yet.

- [ ] **Step 3: Add source constant**

Modify `backend/app/core/constant.py` by adding this line after `SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT`:

```python
SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA = "made_in_china_tianyancha"
```

- [ ] **Step 4: Allow the new source type in schemas**

Modify `backend/app/model/schema.py`.

No new imported name is required for defaults. Add the literal value `"made_in_china_tianyancha"` to both `TaskCreateDTO.source_type` and `CollectedLeadDTO.source_type` Literal lists:

```python
        "alibaba_1688_page_import",
        "made_in_china_tianyancha",
```

- [ ] **Step 5: Add TaskService source handling**

Modify `backend/app/service/task_service.py`.

Add the import near the other source imports:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
```

Add the source to `PUBLIC_WEB_ONLY_SOURCE_TYPE_SET`:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
```

Add the source name to `PUBLIC_ENTERPRISE_SOURCE_NAME_MAP`:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA: "中国制造网+天眼查",
```

Add browser-profile busy checking in `assert_task_browser_profile_available` after the 1688 branch:

```python
        if source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            config = get_config()
            user_data_dir = config.qcc_public_web_user_data_dir.parent / "made-in-china"
            process_id_list = list_browser_profile_process_id(user_data_dir)
            if not process_id_list:
                return
            process_text = ", ".join(str(process_id) for process_id in process_id_list)
            raise RuntimeError(
                f"中国制造网采集浏览器资料目录正在被占用，请先关闭采集浏览器后再启动任务。当前占用进程：{process_text}"
            )
```

Add task-name branch in `build_task_name` before the page assistant branch:

```python
        elif source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            source_name = "中国制造网+天眼查"
```

Add empty-result diagnosis before the generic public enterprise block:

```python
        if task["source_type"] == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            diagnostic_message = getattr(collector, "last_collect_diagnostic", "")
            self.repository.insert_task_event(
                task_id,
                "warning",
                diagnostic_message
                or f"中国制造网本次未采集到公司信息；当前关键词：{keyword_text}。请换更具体的产品词，例如手机壳工厂、数据线厂家，并确认页面没有访问限制。",
            )
            return
```

- [ ] **Step 6: Add China Made warmup service**

Modify `backend/app/service/task_service.py`.

Add this method after `start_alibaba_1688_warmup`:

```python
    def start_made_in_china_warmup(self) -> Dict:
        config = get_config()
        backend_dir = Path(__file__).resolve().parents[2]
        user_data_dir = config.qcc_public_web_user_data_dir.parent / "made-in-china"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        process_id_list = list_browser_profile_process_id(user_data_dir)
        if process_id_list:
            process_text = ", ".join(str(process_id) for process_id in process_id_list)
            raise RuntimeError(f"中国制造网预登录浏览器已打开，请先完成登录/验证并关闭该浏览器。当前占用进程：{process_text}")

        stdout_path = config.log_dir / "made_in_china_warmup.out.log"
        stderr_path = config.log_dir / "made_in_china_warmup.err.log"
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(backend_dir)
        try:
            with stdout_path.open("a", encoding="utf-8") as stdout_file, stderr_path.open(
                "a",
                encoding="utf-8",
            ) as stderr_file:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "app.util.browser_warmup_runner",
                        "--source-type",
                        SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
                    ],
                    cwd=backend_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    creationflags=creation_flags,
                )
        except OSError as ex:
            raise RuntimeError(f"中国制造网预登录浏览器启动失败：{ex}") from ex
        return {
            "source_type": SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            "process_id": process.pid,
            "warmup_url": "https://cn.made-in-china.com/",
            "message": "中国制造网预登录浏览器已打开；请完成登录/验证码/安全校验后关闭该浏览器，再启动采集任务。",
        }
```

- [ ] **Step 7: Add China Made warmup runner support**

Modify `backend/app/util/browser_warmup_runner.py`.

Change the source-type import:

```python
from app.core.constant import SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB
```

to:

```python
from app.core.constant import (
    SOURCE_TYPE_ALIBABA_1688,
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
)
```

Add this branch in `build_warmup_config` before the final `raise RuntimeError`:

```python
    if source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
        return {
            "display_name": "made-in-china",
            "url": "https://cn.made-in-china.com/",
            "user_data_dir": config.qcc_public_web_user_data_dir.parent / "made-in-china",
            "browser_channel": config.qcc_public_web_browser_channel,
            "page_timeout_ms": config.qcc_public_web_page_timeout_ms,
        }
```

- [ ] **Step 8: Add warmup API route**

Modify `backend/app/api/routes.py`.

Add this route after `/browser-warmup/1688`:

```python
@router.post("/browser-warmup/made-in-china")
def start_made_in_china_warmup():
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再打开中国制造网预登录")
    try:
        return task_service.start_made_in_china_warmup()
    except RuntimeError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
```

- [ ] **Step 9: Add repository source group**

Modify `backend/app/repository/lead_repository.py`.

Add the import:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
```

Add a group to `SOURCE_GROUP_TYPE_MAP`:

```python
    "made_in_china": (SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,),
```

- [ ] **Step 10: Add export source handling**

Modify `backend/app/service/export_service.py`.

Add the import:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
```

Add it to `TIANYANCHA_EXPORT_SOURCE_TYPE_SET`:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
```

- [ ] **Step 11: Run source-type tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_source_type -v
```

Expected: PASS, 5 tests.

- [ ] **Step 12: Commit source plumbing if git is available**

Run:

```powershell
git rev-parse --show-toplevel
```

Expected in this workspace: `fatal: not a git repository`. If a future worker runs inside a git repo, commit:

```powershell
git add backend/app/core/constant.py backend/app/model/schema.py backend/app/service/task_service.py backend/app/util/browser_warmup_runner.py backend/app/api/routes.py backend/app/repository/lead_repository.py backend/app/service/export_service.py backend/tests/test_made_in_china_source_type.py
git commit -m "feat: add made in china source type plumbing"
```

## Task 2: Pure China Made Parser

**Files:**
- Create: `backend/tests/test_made_in_china_collector.py`
- Modify: `backend/app/service/collector_service.py`

- [ ] **Step 1: Write failing parser tests**

Create `backend/tests/test_made_in_china_collector.py`:

```python
import unittest

from app.core.constant import SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA
from app.model.schema import CollectedLeadDTO
from app.service.collector_service import MadeInChinaPublicPageCollector, MadeInChinaTianyanchaCollector


class MadeInChinaPublicPageCollectorTest(unittest.TestCase):
    def test_build_leads_from_snapshot_extracts_company_names(self):
        collector = MadeInChinaPublicPageCollector()
        snapshot_list = [
            {
                "text": "佛山市贝丽思电子科技有限公司 身份认证 主营产品：3C配件 手机保护壳 公司地址：广东省 佛山市",
                "href": "https://bls.cn.made-in-china.com/",
            },
            {
                "text": "东莞市妙帝电子科技有限公司 身份认证 主营产品：流沙手机壳 液体手机保护套 公司地址：广东省 东莞市",
                "href": "https://miaodi.cn.made-in-china.com/",
            },
        ]

        lead_list = collector.build_leads_from_snapshot_list(
            industry="3C数码",
            source_keyword="手机壳工厂",
            snapshot_list=snapshot_list,
            collect_limit=10,
        )

        self.assertEqual([lead.suspected_company_name for lead in lead_list], [
            "佛山市贝丽思电子科技有限公司",
            "东莞市妙帝电子科技有限公司",
        ])
        self.assertEqual(lead_list[0].source_type, SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)
        self.assertEqual(lead_list[0].source_keyword, "手机壳工厂")
        self.assertEqual(lead_list[0].profile_url, "https://bls.cn.made-in-china.com/")
        self.assertIn("中国制造网华南公司信息页", lead_list[0].region_text)

    def test_build_leads_from_snapshot_filters_product_and_navigation_noise(self):
        collector = MadeInChinaPublicPageCollector()
        snapshot_list = [
            {"text": "手机壳工厂 产品信息 公司信息 华南 发布询价单", "href": ""},
            {"text": "中国制造网 Made-in-China 首页 热门产品 采购信息", "href": ""},
            {"text": "深圳市华南星电子有限公司 主营产品：手机壳 手机套 公司地址：广东省 深圳市", "href": ""},
        ]

        lead_list = collector.build_leads_from_snapshot_list(
            industry="3C数码",
            source_keyword="手机壳工厂",
            snapshot_list=snapshot_list,
            collect_limit=10,
        )

        self.assertEqual(len(lead_list), 1)
        self.assertEqual(lead_list[0].suspected_company_name, "深圳市华南星电子有限公司")


class MadeInChinaTianyanchaCollectorTest(unittest.TestCase):
    def test_combination_collector_merges_tianyancha_enrichment(self):
        china_lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword="手机壳工厂",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
            product_name="3C配件 手机保护壳",
            profile_url="https://bls.cn.made-in-china.com/",
            region_text="中国制造网华南公司信息页 广东省 佛山市",
        )
        tianyancha_lead = CollectedLeadDTO(
            source_type="tianyancha_public_web",
            source_keyword="佛山市贝丽思电子科技有限公司",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
            phone="0757-88888888",
            phone_source="天眼查公开页可见字段",
            legal_person="张三",
            company_status="存续",
            business_scope="电子产品销售；手机配件制造",
            registered_address="广东省佛山市南海区大沥镇风秀工业区8号",
        )

        collector = MadeInChinaTianyanchaCollector(
            made_in_china_collector=FakeMadeInChinaCollector([china_lead]),
            tianyancha_collector=FakeTianyanchaCollector([tianyancha_lead]),
        )

        lead_list = collector.collect("3C数码", ["手机壳工厂"], 5)

        self.assertEqual(len(lead_list), 1)
        self.assertEqual(lead_list[0].source_type, SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA)
        self.assertEqual(lead_list[0].phone, "0757-88888888")
        self.assertEqual(lead_list[0].legal_person, "张三")
        self.assertEqual(lead_list[0].registered_address, "广东省佛山市南海区大沥镇风秀工业区8号")

    def test_combination_collector_keeps_candidate_when_tianyancha_fails(self):
        china_lead = CollectedLeadDTO(
            source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
            source_keyword="手机壳工厂",
            industry="3C数码",
            suspected_company_name="佛山市贝丽思电子科技有限公司",
        )

        collector = MadeInChinaTianyanchaCollector(
            made_in_china_collector=FakeMadeInChinaCollector([china_lead]),
            tianyancha_collector=FailingTianyanchaCollector(),
        )

        lead_list = collector.collect("3C数码", ["手机壳工厂"], 5)

        self.assertEqual(len(lead_list), 1)
        self.assertEqual(lead_list[0].suspected_company_name, "佛山市贝丽思电子科技有限公司")
        self.assertIn("天眼查待补全", lead_list[0].risk_tag)


class FakeMadeInChinaCollector:
    def __init__(self, lead_list):
        self.lead_list = lead_list
        self.task_event_callback = None
        self.last_collect_diagnostic = ""

    def collect(self, industry, keywords, collect_limit):
        return self.lead_list[:collect_limit]

    def set_task_event_callback(self, callback):
        self.task_event_callback = callback

    def set_existing_lead_identity_list(self, identity_list):
        self.identity_list = identity_list


class FakeTianyanchaCollector:
    def __init__(self, lead_list):
        self.lead_list = lead_list
        self.task_event_callback = None

    def collect_by_company_names(self, industry, company_name_list, collect_limit):
        return self.lead_list[:collect_limit]

    def set_task_event_callback(self, callback):
        self.task_event_callback = callback


class FailingTianyanchaCollector(FakeTianyanchaCollector):
    def __init__(self):
        super().__init__([])

    def collect_by_company_names(self, industry, company_name_list, collect_limit):
        raise RuntimeError("模拟天眼查访问限制")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run parser tests to verify they fail**

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_collector -v
```

Expected: FAIL because `MadeInChinaPublicPageCollector` and `MadeInChinaTianyanchaCollector` are not defined.

- [ ] **Step 3: Add China Made constants and candidate class**

Modify `backend/app/service/collector_service.py`.

Add the new import near the other source constants:

```python
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
```

Add constants near the 1688 constants:

```python
MADE_IN_CHINA_BLOCKED_TEXT_TOKEN_LIST = [
    "请完成验证",
    "安全验证",
    "请输入验证码",
    "访问过于频繁",
    "访问被拒绝",
    "登录后继续",
]

MADE_IN_CHINA_SKIP_TEXT_TOKEN_LIST = [
    "中国制造网",
    "Made-in-China",
    "首页",
    "产品信息",
    "公司信息",
    "采购信息",
    "热门产品",
    "发布询价单",
    "在线交谈",
    "发联系信",
    "查看更多公司信息",
]

MADE_IN_CHINA_PROFILE_HOST_SUFFIX_LIST = (
    ".cn.made-in-china.com",
    ".made-in-china.com",
)
```

Add this dataclass near other candidate dataclasses:

```python
@dataclass
class MadeInChinaCandidate:
    company_name: str
    product_name: str
    profile_url: str
    region_text: str
    source_keyword: str
```

- [ ] **Step 4: Add pure parser methods**

Add `MadeInChinaPublicPageCollector` before `Alibaba1688TianyanchaCollector` in `backend/app/service/collector_service.py`:

```python
class MadeInChinaPublicPageCollector:
    def __init__(self):
        self.config = get_config()
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None
        self.last_collect_diagnostic = ""
        self.existing_dedupe_key_set = set()

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.existing_dedupe_key_set = set()
        for identity in identity_list:
            for field_name in ("company_name", "suspected_company_name", "profile_url", "shop_url"):
                key = self.normalize_dedupe_text(str(identity.get(field_name) or ""))
                if key:
                    self.existing_dedupe_key_set.add(key)

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        self.task_event_callback(event_type, level, message)

    def build_leads_from_snapshot_list(
        self,
        industry: str,
        source_keyword: str,
        snapshot_list: List[Dict[str, str]],
        collect_limit: int,
    ) -> List[CollectedLeadDTO]:
        result_list: List[CollectedLeadDTO] = []
        dedupe_set = set()
        for snapshot in snapshot_list:
            candidate = self.build_candidate_from_snapshot(industry, source_keyword, snapshot)
            if candidate is None:
                continue
            dedupe_key = self.normalize_dedupe_text(candidate.company_name)
            if not dedupe_key or dedupe_key in dedupe_set or dedupe_key in self.existing_dedupe_key_set:
                continue
            dedupe_set.add(dedupe_key)
            lead = CollectedLeadDTO(
                source_type=SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
                source_keyword=source_keyword,
                industry=industry,
                suspected_company_name=candidate.company_name,
                product_name=candidate.product_name,
                profile_url=candidate.profile_url,
                shop_url=candidate.profile_url,
                phone_source="中国制造网公开公司列表未展示电话，待天眼查补全",
                region_text=candidate.region_text,
                risk_tag="天眼查待补全",
                is_enterprise_verified=True,
            )
            result_list.append(lead)
            if len(result_list) >= collect_limit:
                break
        return result_list

    def build_candidate_from_snapshot(
        self,
        industry: str,
        source_keyword: str,
        snapshot: Dict[str, str],
    ) -> Optional[MadeInChinaCandidate]:
        text = self.clean_text(snapshot.get("text", ""))
        if not text or self.is_blocked_text(text):
            return None
        company_name = self.extract_company_name(text)
        if not self.is_valid_company_name(company_name, source_keyword):
            return None
        href = self.clean_url(snapshot.get("href", ""))
        product_name = self.extract_product_name(text, source_keyword)
        region_text = f"中国制造网华南公司信息页 {text}"[:3000]
        return MadeInChinaCandidate(
            company_name=company_name,
            product_name=product_name,
            profile_url=href,
            region_text=region_text,
            source_keyword=source_keyword,
        )

    def extract_company_name(self, text: str) -> str:
        for company_name in COMPANY_NAME_PATTERN.findall(text or ""):
            clean_name = clean_company_name_text(company_name)
            if self.is_valid_company_name(clean_name, ""):
                return clean_name
        return ""

    def is_valid_company_name(self, company_name: str, source_keyword: str) -> bool:
        clean_name = clean_company_name_text(company_name)
        if not clean_name:
            return False
        if clean_name in INVALID_COMPANY_NAME_SET or clean_name == source_keyword:
            return False
        if KEYWORD_ONLY_COMPANY_PATTERN.fullmatch(clean_name):
            return False
        if has_any_token(clean_name, MADE_IN_CHINA_SKIP_TEXT_TOKEN_LIST):
            return False
        if not clean_name.endswith(REAL_COMPANY_STRONG_SUFFIX_TUPLE + FACTORY_COMPANY_SUFFIX_TUPLE):
            return False
        if clean_name.endswith(FACTORY_COMPANY_SUFFIX_TUPLE) and has_any_token(clean_name, GENERIC_FACTORY_NAME_TOKEN_LIST):
            return False
        return True

    def extract_product_name(self, text: str, source_keyword: str) -> str:
        match = re.search(r"(?:主营产品|供应产品|主营)[:：\s]*([^。；;\n]{2,80})", text or "")
        if match:
            return self.clean_text(match.group(1))[:120]
        return self.clean_text(source_keyword)[:120]

    def is_blocked_text(self, text: str) -> bool:
        return has_any_token(text, MADE_IN_CHINA_BLOCKED_TEXT_TOKEN_LIST)

    def clean_url(self, url: str) -> str:
        clean_url = str(url or "").strip()
        if clean_url.startswith("//"):
            return f"https:{clean_url}"
        if clean_url.startswith("/"):
            return f"https://cn.made-in-china.com{clean_url}"
        return clean_url

    def normalize_dedupe_text(self, value: str) -> str:
        return clean_company_name_text(value) or self.clean_text(value)

    def clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
```

- [ ] **Step 5: Run parser tests for current expected partial pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_collector.MadeInChinaPublicPageCollectorTest -v
```

Expected: PASS for the two pure parser tests.

- [ ] **Step 6: Commit parser if git is available**

Run:

```powershell
git rev-parse --show-toplevel
```

Expected in this workspace: `fatal: not a git repository`. If git is available:

```powershell
git add backend/app/service/collector_service.py backend/tests/test_made_in_china_collector.py
git commit -m "feat: parse china made company candidates"
```

## Task 3: Combination Collector and Factory Wiring

**Files:**
- Modify: `backend/app/service/collector_service.py`

- [ ] **Step 1: Run combination tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_collector.MadeInChinaTianyanchaCollectorTest -v
```

Expected: FAIL because `MadeInChinaTianyanchaCollector` is not defined.

- [ ] **Step 2: Add combination collector**

Add this class before `AiWebSearchCollector` or near `Alibaba1688TianyanchaCollector` in `backend/app/service/collector_service.py`:

```python
class MadeInChinaTianyanchaCollector:
    def __init__(self, made_in_china_collector=None, tianyancha_collector=None):
        self.made_in_china_collector = made_in_china_collector or MadeInChinaPublicPageCollector()
        self.tianyancha_collector = tianyancha_collector or EnterprisePublicWebCollector.create_tianyancha_collector()
        self.task_event_callback: Optional[Callable[[str, str, str], None]] = None
        self.last_collect_diagnostic = ""

    def __getattr__(self, name: str):
        return getattr(self.made_in_china_collector, name)

    def set_task_event_callback(self, callback: Callable[[str, str, str], None]) -> None:
        self.task_event_callback = callback
        self.made_in_china_collector.set_task_event_callback(callback)
        self.tianyancha_collector.set_task_event_callback(callback)

    def set_existing_lead_identity_list(self, identity_list: List[Dict]) -> None:
        self.made_in_china_collector.set_existing_lead_identity_list(identity_list)

    def emit_task_event(self, event_type: str, level: str, message: str) -> None:
        if self.task_event_callback is None:
            return
        self.task_event_callback(event_type, level, message)

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        china_lead_list = self.made_in_china_collector.collect(industry, keywords, collect_limit)
        self.last_collect_diagnostic = getattr(self.made_in_china_collector, "last_collect_diagnostic", "")
        if not china_lead_list:
            return []
        self.emit_task_event(
            "collecting",
            "info",
            f"中国制造网已采集 {len(china_lead_list)} 条公开公司候选，开始用天眼查按企业名补全法人和电话。",
        )
        try:
            tianyancha_lead_list = self.tianyancha_collector.collect_by_company_names(
                industry=industry,
                company_name_list=[lead.suspected_company_name for lead in china_lead_list],
                collect_limit=len(china_lead_list),
            )
        except Exception as ex:
            logger.exception("Made-in-China Tianyancha enrichment failed, error=%s", ex)
            for lead in china_lead_list:
                lead.source_type = SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA
                lead.risk_tag = self.merge_text(lead.risk_tag, "天眼查待补全")
            self.emit_task_event(
                "collecting",
                "warning",
                f"天眼查补全失败，系统将先保留中国制造网候选企业；原因：{ex}",
            )
            return china_lead_list
        enrichment_map = self.build_enrichment_map(tianyancha_lead_list)
        enriched_count = 0
        for china_lead in china_lead_list:
            china_lead.source_type = SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA
            enrichment = self.find_enrichment_lead(china_lead.suspected_company_name, enrichment_map)
            if enrichment is None:
                china_lead.risk_tag = self.merge_text(china_lead.risk_tag, "天眼查待补全")
                continue
            self.merge_enrichment(china_lead, enrichment)
            enriched_count += 1
        self.emit_task_event("collecting", "info", f"中国制造网候选企业天眼查补全完成：匹配 {enriched_count} 条。")
        return china_lead_list

    def build_enrichment_map(self, lead_list: List[CollectedLeadDTO]) -> Dict[str, CollectedLeadDTO]:
        result = {}
        for lead in lead_list:
            key = EnterprisePublicWebCollector.normalize_company_match_key(lead.suspected_company_name)
            if key and key not in result:
                result[key] = lead
        return result

    def find_enrichment_lead(
        self,
        company_name: str,
        enrichment_map: Dict[str, CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        key = EnterprisePublicWebCollector.normalize_company_match_key(company_name)
        return enrichment_map.get(key)

    def merge_enrichment(self, target: CollectedLeadDTO, source: CollectedLeadDTO) -> None:
        if has_public_phone_text(source.phone):
            target.phone = self.merge_text(target.phone, source.phone)
            target.phone_source = self.merge_text(target.phone_source, source.phone_source or "天眼查公开页可见字段")
        if is_valid_contact_name(source.contact_name):
            target.contact_name = source.contact_name
        elif not target.contact_name and is_valid_contact_name(source.legal_person):
            target.contact_name = source.legal_person
        for field_name in ("legal_person", "company_status", "business_scope", "registered_address", "risk_tag"):
            if getattr(source, field_name):
                setattr(target, field_name, getattr(source, field_name))
        target.region_text = self.merge_text(target.region_text, source.region_text)[:3000]
        target.is_enterprise_verified = target.is_enterprise_verified or source.is_enterprise_verified
        target.source_type = SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA

    def merge_text(self, left: str, right: str) -> str:
        result = []
        seen = set()
        for value in (left, right):
            for item in re.split(r"[；;,，]+", value or ""):
                clean_item = item.strip()
                if not clean_item or clean_item in seen:
                    continue
                seen.add(clean_item)
                result.append(clean_item)
        return "；".join(result)
```

- [ ] **Step 3: Wire the factory**

Modify `CollectorFactory.get_collector` in `backend/app/service/collector_service.py` by adding this branch before the 1688 branch:

```python
        if source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            return MadeInChinaTianyanchaCollector()
```

- [ ] **Step 4: Run all backend unit tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_source_type tests.test_made_in_china_collector -v
```

Expected: PASS.

- [ ] **Step 5: Commit combination collector if git is available**

Run:

```powershell
git rev-parse --show-toplevel
```

Expected in this workspace: `fatal: not a git repository`. If git is available:

```powershell
git add backend/app/service/collector_service.py backend/tests/test_made_in_china_collector.py
git commit -m "feat: add china made tianyancha collector"
```

## Task 4: China Made Browser Automation

**Files:**
- Modify: `backend/app/service/collector_service.py`

- [ ] **Step 1: Add failing automation-shape test**

Append this test method to `MadeInChinaPublicPageCollectorTest` in `backend/tests/test_made_in_china_collector.py`:

```python
    def test_search_keyword_list_keeps_user_terms_and_defaults(self):
        collector = MadeInChinaPublicPageCollector()

        self.assertEqual(
            collector.build_search_keyword_list("3C数码", ["手机壳工厂", "数据线厂家"]),
            ["手机壳工厂", "数据线厂家"],
        )
        self.assertIn("手机壳工厂", collector.build_search_keyword_list("3C数码", []))
```

- [ ] **Step 2: Run automation-shape test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_collector.MadeInChinaPublicPageCollectorTest.test_search_keyword_list_keeps_user_terms_and_defaults -v
```

Expected: FAIL because `build_search_keyword_list` is missing.

- [ ] **Step 3: Add keyword and browser methods**

Add these methods inside `MadeInChinaPublicPageCollector`:

```python
    def build_search_keyword_list(self, industry: str, keywords: List[str]) -> List[str]:
        raw_keyword_list = []
        for keyword in keywords:
            raw_keyword_list.extend(re.split(r"[,，、;/\n\r]+", keyword or ""))
        if not raw_keyword_list:
            raw_keyword_list = INDUSTRY_PUBLIC_SEARCH_KEYWORD_MAP.get(industry, [industry])
        result = []
        for keyword in raw_keyword_list:
            clean_keyword = self.clean_text(keyword)
            if not clean_keyword or self.has_mojibake(clean_keyword):
                continue
            if not self.build_business_token_list(clean_keyword) and not self.is_company_name_keyword(clean_keyword):
                clean_keyword = f"{clean_keyword}工厂"
            if clean_keyword not in result:
                result.append(clean_keyword)
        return result

    def has_mojibake(self, value: str) -> bool:
        return has_any_token(value, MOJIBAKE_TOKEN_LIST)

    def build_business_token_list(self, value: str) -> List[str]:
        return [token for token in BUSINESS_KEYWORD_LIST if token in value]

    def is_company_name_keyword(self, value: str) -> bool:
        return bool(COMPANY_NAME_PATTERN.search(value or ""))

    def collect(self, industry: str, keywords: List[str], collect_limit: int) -> List[CollectedLeadDTO]:
        if sync_playwright is None:
            raise RuntimeError("缺少 Playwright 依赖，请先在 backend 目录执行：.\\.venv\\Scripts\\python -m pip install -r requirements.txt")
        self.last_collect_diagnostic = ""
        keyword_list = self.build_search_keyword_list(industry, keywords)
        if not keyword_list:
            raise RuntimeError(f"中国制造网采集关键词无效：当前行业为“{industry}”，请填写具体产品词，例如“手机壳工厂、数据线厂家”。")
        result_list: List[CollectedLeadDTO] = []
        with sync_playwright() as playwright:
            context = self.launch_context(playwright)
            page = context.new_page()
            try:
                for keyword in keyword_list:
                    if len(result_list) >= collect_limit:
                        break
                    self.goto_search_page(page, keyword)
                    self.switch_to_company_tab(page)
                    self.select_south_china_region(page)
                    snapshot_list = self.extract_company_snapshot_list(page)
                    lead_list = self.build_leads_from_snapshot_list(
                        industry=industry,
                        source_keyword=keyword,
                        snapshot_list=snapshot_list,
                        collect_limit=collect_limit - len(result_list),
                    )
                    result_list.extend(lead_list)
                    self.wait_between_keyword()
            finally:
                context.close()
        if not result_list:
            self.last_collect_diagnostic = f"中国制造网本次未采集到公司信息；关键词：{', '.join(keyword_list[:6])}。"
        return result_list[:collect_limit]

    def launch_context(self, playwright):
        user_data_dir = self.config.qcc_public_web_user_data_dir.parent / "made-in-china"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        context_args = {
            "headless": self.config.qcc_public_web_headless,
            "viewport": {"width": 1440, "height": 900},
            "locale": "zh-CN",
        }
        if self.config.qcc_public_web_browser_channel:
            context_args["channel"] = self.config.qcc_public_web_browser_channel
        return playwright.chromium.launch_persistent_context(str(user_data_dir), **context_args)

    def goto_search_page(self, page, keyword: str) -> None:
        page.goto("https://cn.made-in-china.com/", wait_until="domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
        page.wait_for_timeout(1200)
        self.assert_page_allowed(page)
        search_input = page.locator("input[type='text'], input[placeholder*='产品'], input[placeholder*='名称']").first
        search_input.fill(keyword)
        search_button = page.locator("button:has-text('搜索'), input[type='submit'], a:has-text('搜索')").first
        search_button.click()
        page.wait_for_load_state("domcontentloaded", timeout=self.config.qcc_public_web_page_timeout_ms)
        page.wait_for_timeout(1800)
        self.assert_page_allowed(page)

    def switch_to_company_tab(self, page) -> None:
        tab = page.locator("a:has-text('公司信息'), button:has-text('公司信息'), span:has-text('公司信息')").first
        if tab.count() > 0:
            tab.click()
            page.wait_for_timeout(1800)
            self.assert_page_allowed(page)
            return
        self.emit_task_event("collecting", "warning", "中国制造网未找到公司信息标签，系统将尝试从当前可见列表抽取公司名。")

    def select_south_china_region(self, page) -> None:
        region_trigger = page.locator("text=所有地区").first
        if region_trigger.count() > 0:
            region_trigger.click()
            page.wait_for_timeout(600)
        south_china = page.locator("a:has-text('华南'), button:has-text('华南'), span:has-text('华南')").first
        if south_china.count() > 0:
            south_china.click()
            page.wait_for_timeout(1800)
            self.assert_page_allowed(page)
            return
        self.emit_task_event("collecting", "warning", "中国制造网未确认华南筛选，后续将以天眼查注册地址确认广东。")

    def extract_company_snapshot_list(self, page) -> List[Dict[str, str]]:
        self.scroll_result_page(page)
        return page.evaluate(
            """
            () => {
              const companyPattern = /(有限责任公司|股份有限公司|集团有限公司|有限公司|合伙企业|个人独资企业|分公司|商行|经营部|工作室|工厂|厂)/;
              const nodeList = Array.from(document.querySelectorAll('li, div, tr, section, article'));
              const result = [];
              const seen = new Set();
              for (const node of nodeList) {
                const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!text || text.length < 8 || text.length > 1200 || !companyPattern.test(text)) {
                  continue;
                }
                const link = Array.from(node.querySelectorAll('a')).find((item) => {
                  const href = item.href || item.getAttribute('href') || '';
                  return href.includes('made-in-china.com');
                });
                const href = link ? (link.href || link.getAttribute('href') || '') : '';
                const key = `${text.slice(0, 160)}|${href}`;
                if (seen.has(key)) {
                  continue;
                }
                seen.add(key);
                result.push({ text, href });
                if (result.length >= 80) {
                  break;
                }
              }
              return result;
            }
            """
        )

    def scroll_result_page(self, page) -> None:
        page.evaluate(
            """
            async () => {
              const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
              for (let index = 0; index < 4; index += 1) {
                window.scrollBy(0, Math.max(700, window.innerHeight * 0.85));
                await sleep(500);
              }
              window.scrollTo(0, 0);
              await sleep(300);
            }
            """
        )

    def assert_page_allowed(self, page) -> None:
        page_text = self.clean_text(page.locator("body").inner_text(timeout=3000))
        if has_any_token(page_text, MADE_IN_CHINA_BLOCKED_TEXT_TOKEN_LIST):
            raise RuntimeError("中国制造网页面出现验证码、访问过频或安全校验，请先在前端点击预登录中国制造网，完成登录/验证并关闭浏览器后再启动采集。")

    def wait_between_keyword(self) -> None:
        time.sleep(max(2.0, self.config.qcc_public_web_request_interval_seconds))
```

- [ ] **Step 4: Run backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_source_type tests.test_made_in_china_collector -v
```

Expected: PASS.

- [ ] **Step 5: Run a smoke import**

Run:

```powershell
.\.venv\Scripts\python.exe -c "from app.service.collector_service import MadeInChinaPublicPageCollector; c=MadeInChinaPublicPageCollector(); print(c.build_search_keyword_list('3C数码', ['手机壳工厂']))"
```

Expected:

```text
['手机壳工厂']
```

- [ ] **Step 6: Commit browser automation if git is available**

Run:

```powershell
git rev-parse --show-toplevel
```

Expected in this workspace: `fatal: not a git repository`. If git is available:

```powershell
git add backend/app/service/collector_service.py backend/tests/test_made_in_china_collector.py
git commit -m "feat: automate china made company search"
```

## Task 5: Frontend Source Choices and Display

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/TaskComposer.vue`
- Modify: `frontend/src/utils/format.ts`
- Modify: `frontend/src/components/LeadTable.vue`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add China Made warmup API client**

Modify `frontend/src/api/client.ts`.

Add this function after `warmupAlibaba1688Browser`:

```ts
export function warmupMadeInChinaBrowser() {
  return requestJson<BrowserWarmupResult>('/browser-warmup/made-in-china', {
    method: 'POST',
  });
}
```

- [ ] **Step 2: Update source buttons and warmup behavior**

Modify `frontend/src/components/TaskComposer.vue`.

Add `warmupMadeInChinaBrowser` to the API import:

```ts
  warmupAlibaba1688Browser,
  warmupMadeInChinaBrowser,
  warmupTianyanchaBrowser,
```

Replace `publicWebSourceTypeList` with:

```ts
const publicWebSourceTypeList = [
  'qixin_public_web',
  'tianyancha_public_web',
  'ai_web_search',
  'alibaba_1688',
  'made_in_china_tianyancha',
];
```

Replace `sourceButtonList` with:

```ts
const sourceButtonList = [
  { value: 'qixin_public_web', label: '启信宝' },
  { value: 'tianyancha_public_web', label: '天眼查' },
  { value: 'ai_web_search', label: 'AI 1688搜企' },
  { value: 'alibaba_1688', label: '1688 + 天眼查' },
  { value: 'made_in_china_tianyancha', label: '中国制造网 + 天眼查' },
];
```

Add:

```ts
const isMadeInChinaSource = computed(() => formData.source_type === 'made_in_china_tianyancha');
```

Change `canWarmupBrowser` to include China Made:

```ts
const canWarmupBrowser = computed(() => isTianyanchaSource.value || isAlibaba1688Source.value || isMadeInChinaSource.value);
```

Change `warmupButtonText` to:

```ts
const warmupButtonText = computed(() => {
  if (isWarmupStarting.value) {
    return '正在打开预登录浏览器';
  }
  if (isAlibaba1688Source.value) {
    return '预登录1688';
  }
  if (isMadeInChinaSource.value) {
    return '预登录中国制造网';
  }
  return '预热天眼查验证';
});
```

Add a keyword guide branch before the 1688 branch:

```ts
  if (formData.source_type === 'made_in_china_tianyancha') {
    return '先预登录中国制造网以保留登录/验证状态，再从公开公司列表提取企业名并筛选华南；最后进入天眼查补全法人、联系电话和注册地址。';
  }
```

Change the enterprise-public-page condition:

```ts
  if (['aiqicha_public_web', 'qixin_public_web', 'tianyancha_public_web'].includes(formData.source_type)) {
```

to:

```ts
  if (['qixin_public_web', 'tianyancha_public_web'].includes(formData.source_type)) {
```

Replace `startBrowserWarmup` with:

```ts
async function startBrowserWarmup() {
  isWarmupStarting.value = true;
  warmupMessage.value = '';
  try {
    const result = isAlibaba1688Source.value
      ? await warmupAlibaba1688Browser()
      : isMadeInChinaSource.value
        ? await warmupMadeInChinaBrowser()
        : await warmupTianyanchaBrowser();
    warmupMessage.value = result.message;
  } catch (error) {
    const message = error instanceof Error ? error.message : '预登录浏览器启动失败。';
    warmupMessage.value = message;
    window.alert(message);
  } finally {
    isWarmupStarting.value = false;
  }
}
```

- [ ] **Step 3: Update source display formatter**

Modify `frontend/src/utils/format.ts`.

Add this entry to `sourceTypeMap`:

```ts
    made_in_china_tianyancha: '中国制造网+天眼查',
```

Add this replacement to `formatTaskName` before the 1688 replacement:

```ts
    .replace(/中国制造网公开页/g, '中国制造网')
```

- [ ] **Step 4: Update lead source tabs**

Modify `frontend/src/components/LeadTable.vue`.

Replace `sourceGroupDefinitionList` with:

```ts
const sourceGroupDefinitionList = [
  { key: 'all', label: '全部线索' },
  { key: 'qixin', label: '启信宝' },
  { key: 'tianyancha', label: '天眼查' },
  { key: 'ai_web', label: 'AI 1688搜企' },
  { key: 'douyin', label: '抖音+企查查' },
  { key: 'alibaba_tianyancha', label: '1688+天眼查' },
  { key: 'made_in_china', label: '中国制造网+天眼查' },
  { key: 'alibaba', label: '1688普通页面' },
];
```

- [ ] **Step 5: Update app heading copy**

Modify `frontend/src/App.vue`.

Change:

```vue
          <p>本地轻量版 · 企查查 / 爱企查 / 启信宝 / 天眼查 / 抖音线索 / 1688</p>
```

to:

```vue
          <p>本地轻量版 · 启信宝 / 天眼查 / 1688 / 中国制造网</p>
```

- [ ] **Step 6: Run frontend build**

Run from `frontend`:

```powershell
npm.cmd run build
```

Expected: PASS with `vue-tsc --noEmit && vite build`.

- [ ] **Step 7: Verify visible source labels by grep**

Run from repo root:

```powershell
rg -n "企查查|爱企查|中国制造网 \\+ 天眼查|made_in_china_tianyancha" frontend\\src\\components\\TaskComposer.vue frontend\\src\\components\\LeadTable.vue frontend\\src\\utils\\format.ts frontend\\src\\App.vue
```

Expected:

- `TaskComposer.vue` contains `中国制造网 + 天眼查`.
- `TaskComposer.vue` contains `预登录中国制造网`.
- `TaskComposer.vue` does not contain `{ value: 'qcc_public_web'` or `{ value: 'aiqicha_public_web'`.
- `format.ts` may still contain historical display labels for old records.
- `LeadTable.vue` contains `made_in_china` and does not contain visible `qcc` / `aiqicha` tab definitions.

- [ ] **Step 8: Commit frontend source choices if git is available**

Run:

```powershell
git rev-parse --show-toplevel
```

Expected in this workspace: `fatal: not a git repository`. If git is available:

```powershell
git add frontend/src/api/client.ts frontend/src/components/TaskComposer.vue frontend/src/utils/format.ts frontend/src/components/LeadTable.vue frontend/src/App.vue
git commit -m "feat: add china made source in frontend"
```

## Task 6: End-to-End Verification

**Files:**
- No new source files unless verification exposes a defect.

- [ ] **Step 1: Run backend unit tests**

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_made_in_china_source_type tests.test_made_in_china_collector -v
```

Expected: PASS.

- [ ] **Step 2: Run Python compile check**

Run from repo root:

```powershell
python -m compileall -q backend\\app
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run frontend build**

Run from `frontend`:

```powershell
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 4: Restart services**

Run from repo root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\deployment\\windows\\start.ps1
```

Expected: backend listens on `127.0.0.1:8000`, frontend listens on `127.0.0.1:5173`.

- [ ] **Step 5: Verify backend health, warmup, and source type acceptance**

Run:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -Method Get | ConvertTo-Json
```

Expected:

```json
{
  "status": "ok"
}
```

Optionally verify the China Made warmup endpoint when you are ready to close the opened browser:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/browser-warmup/made-in-china' -Method Post | ConvertTo-Json -Depth 5
```

Expected: JSON with `source_type` equal to `made_in_china_tianyancha`, `warmup_url` equal to `https://cn.made-in-china.com/`, and a message telling the user to finish login/verification and close the browser.

Close the China Made warmup browser before creating a task. Then run a low-count task creation only when no active task is running:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/tasks' -Method Post -ContentType 'application/json' -Body '{"source_type":"made_in_china_tianyancha","industry":"3C数码","keywords":["手机壳工厂"],"collect_limit":1,"is_qcc_enabled":false,"qcc_limit":0}' | ConvertTo-Json
```

Expected: JSON with `task_id`. If China Made blocks automated access, the task may finish failed or with zero leads, but API validation must accept the source type and task logs must show China Made diagnostics.

- [ ] **Step 6: Inspect task logs**

Run:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/logs?limit=20' -Method Get | ConvertTo-Json -Depth 5
```

Expected: log messages include one or more of:

- `中国制造网`
- `公司信息`
- `华南`
- `天眼查补全`

- [ ] **Step 7: Verify frontend page**

Open:

```text
http://127.0.0.1:5173/
```

Expected:

- Task form includes `中国制造网 + 天眼查`.
- Task form does not show task-choice buttons for `企查查` or `爱企查`.
- Selecting `中国制造网 + 天眼查` keeps quota disabled and shows `预登录中国制造网`.

- [ ] **Step 8: Record verification outcome**

If all checks pass, summarize:

```text
Backend unit tests: PASS
Python compile: PASS
Frontend build: PASS
Health endpoint: PASS
China Made warmup endpoint: PASS
Task source validation: PASS
China Made live collection: PASS or blocked by public-site access controls
```

If live collection is blocked by access controls, keep the implementation complete and report the exact task log message.
