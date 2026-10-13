import logging
import os
import random
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from app.core.config import get_config
from app.core.constant import (
    ASSIGNMENT_STATUS_UNASSIGNED,
    DEFAULT_QCC_INTERFACE_NAME,
    SOURCE_TYPE_ALIBABA_1688,
    SOURCE_TYPE_ALIBABA_INTERNATIONAL,
    SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT,
    SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
    SOURCE_TYPE_AI_WEB_SEARCH,
    SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
    SOURCE_TYPE_DOUYIN_QCC,
    SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
    SOURCE_TYPE_QIXIN_PUBLIC_WEB,
    SOURCE_TYPE_QCC_PUBLIC_WEB,
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
    TASK_STATUS_COLLECTING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SAVING,
    TASK_STATUS_SCORING,
    TASK_STATUS_VERIFYING,
    TASK_STATUS_WAITING_MANUAL,
    VERIFY_STATUS_QUOTA_LIMITED,
    VERIFY_STATUS_PUBLIC_WEB,
    VERIFY_STATUS_SKIPPED,
)
from app.model.schema import (
    Alibaba1688SnapshotDTO,
    BatchAutomationCreateDTO,
    CollectedLeadDTO,
    CompanyVerifyDTO,
    QixinEnrichmentCreateDTO,
    TaskCreateDTO,
    TianyanchaEnrichmentCreateDTO,
)
from app.repository.lead_repository import LeadRepository
from app.service.collector_service import (
    Alibaba1688SnapshotParser,
    CollectorFactory,
    EnterprisePublicWebCollector,
    get_disqualified_lead_reason,
    get_disqualified_text_reason,
    is_reliable_guangdong_address,
)
from app.service.deepseek_ai_service import DeepSeekAiService
from app.service.qichacha_service import QichachaService
from app.service.qixin_api_service import QixinApiError, QixinApiService
from app.service.scoring_service import ScoringService
from app.util.browser_profile_util import list_browser_profile_process_id, stop_process_id_list
from app.util.phone_filter_util import clean_public_phone_text
from app.util.product_name_util import repair_product_name_for_source
from app.util.region_parse_util import GUANGDONG_CITY_LIST, extract_region_info, normalize_city_name
from app.util.region_util import is_guangdong_text
from app.util.time_util import get_current_time_text

logger = logging.getLogger(__name__)

INDUSTRY_BEAUTY_CARE = "美妆个护"
INDUSTRY_OTHER = "其他"
LEGACY_INDUSTRY_COSMETICS = "化妆品"
INDUSTRY_ALIAS_MAP = {
    LEGACY_INDUSTRY_COSMETICS: INDUSTRY_BEAUTY_CARE,
}
ALLOWED_INDUSTRY_SET = {"3C数码", "服装", INDUSTRY_BEAUTY_CARE, INDUSTRY_OTHER}
GUANGDONG_TARGET_CITY_SET = {
    "广东省",
    *(f"{city_name}市" for city_name in GUANGDONG_CITY_LIST),
}
TARGET_CITY_SOURCE_TYPE_SET = {SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_ALIBABA_INTERNATIONAL}
PUBLIC_WEB_ONLY_SOURCE_TYPE_SET = {
    SOURCE_TYPE_QCC_PUBLIC_WEB,
    SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,
    SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
    SOURCE_TYPE_QIXIN_PUBLIC_WEB,
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
    SOURCE_TYPE_DOUYIN_QCC,
    SOURCE_TYPE_ALIBABA_1688,
    SOURCE_TYPE_ALIBABA_INTERNATIONAL,
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
    SOURCE_TYPE_AI_WEB_SEARCH,
}
PHONE_REQUIRED_SOURCE_TYPE_SET = (
    PUBLIC_WEB_ONLY_SOURCE_TYPE_SET - {SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_ALIBABA_INTERNATIONAL}
) | {
    SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT,
    SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
}
PUBLIC_ENTERPRISE_SOURCE_NAME_MAP = {
    SOURCE_TYPE_QCC_PUBLIC_WEB: "企查查",
    SOURCE_TYPE_FENGNIAO_PUBLIC_WEB: "美亚风鸟",
    SOURCE_TYPE_AIQICHA_PUBLIC_WEB: "爱企查",
    SOURCE_TYPE_QIXIN_PUBLIC_WEB: "启信宝",
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB: "天眼查",
    SOURCE_TYPE_AI_WEB_SEARCH: "AI 1688搜企",
    SOURCE_TYPE_ALIBABA_INTERNATIONAL: "阿里国际站",
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA: "中国制造网+天眼查",
}
ALIBABA_INTERNATIONAL_GUANGDONG_REGION_TOKEN_LIST = (
    "guangdong",
    "guangzhou",
    "shenzhen",
    "zhuhai",
    "shantou",
    "foshan",
    "shaoguan",
    "zhanjiang",
    "zhaoqing",
    "jiangmen",
    "maoming",
    "huizhou",
    "meizhou",
    "shanwei",
    "heyuan",
    "yangjiang",
    "qingyuan",
    "dongguan",
    "zhongshan",
    "chaozhou",
    "jieyang",
    "yunfu",
)
ALIBABA_INTERNATIONAL_CITY_TOKEN_MAP = {
    "广州": "guangzhou",
    "深圳": "shenzhen",
    "珠海": "zhuhai",
    "汕头": "shantou",
    "佛山": "foshan",
    "韶关": "shaoguan",
    "湛江": "zhanjiang",
    "肇庆": "zhaoqing",
    "江门": "jiangmen",
    "茂名": "maoming",
    "惠州": "huizhou",
    "梅州": "meizhou",
    "汕尾": "shanwei",
    "河源": "heyuan",
    "阳江": "yangjiang",
    "清远": "qingyuan",
    "东莞": "dongguan",
    "中山": "zhongshan",
    "潮州": "chaozhou",
    "揭阳": "jieyang",
    "云浮": "yunfu",
}
TIANYANCHA_ENRICHMENT_PACING_PROFILE_MAP = {
    "conservative": {
        "batch_size": 5,
        "cooldown_seconds": 180.0,
        "label": "conservative",
    },
    "standard": {
        "batch_size": 10,
        "cooldown_seconds": 90.0,
        "label": "standard",
    },
    "manual": {
        "batch_size": 3,
        "cooldown_seconds": 240.0,
        "label": "manual handoff",
    },
}

BATCH_CITY_ROTATION_LIST = [
    "深圳",
    "东莞",
    "广州",
    "佛山",
    "惠州",
    "中山",
    "珠海",
    "汕头",
]
BATCH_INDUSTRY_CITY_ROTATION_MAP = {
    "3C数码": ["深圳", "东莞", "广州", "惠州", "佛山", "中山"],
}
BATCH_INDUSTRY_KEYWORD_EXPANSION_MAP = {
    "3C数码": [
        "数据线OEM",
        "Type-C数据线",
        "手机配件",
        "手机壳",
        "充电器OEM",
        "移动电源",
        "蓝牙耳机",
        "数码配件",
        "电子产品",
        "3C配件",
    ],
    "服装": [
        "女装批发",
        "服装OEM",
        "制衣厂",
        "服装加工",
        "跨境服装",
        "童装批发",
        "针织服装",
        "服装供应链",
        "服饰批发",
        "外贸服装",
    ],
    INDUSTRY_BEAUTY_CARE: [
        "护肤品OEM",
        "化妆品工厂",
        "彩妆代工",
        "面膜OEM",
        "日化工厂",
        "美妆供应链",
        "洗护OEM",
        "化妆品包材",
    ],
}
BATCH_SEARCH_INTENT_LIST = ["工厂", "生产厂家", "源头厂家", "供应商", "OEM", "制造商", "代工厂", "批发"]


class TaskService:
    def __init__(self, repository: LeadRepository):
        self.repository = repository
        self.collector_factory = CollectorFactory()
        self.qichacha_service = QichachaService()
        self.qixin_api_service = QixinApiService()
        self.scoring_service = ScoringService()
        self.deepseek_ai_service = DeepSeekAiService()
        self.batch_automation_lock = Lock()
        self.batch_automation_stop_requested = False

    def is_batch_automation_running(self) -> bool:
        return self.batch_automation_lock.locked()

    def reserve_batch_automation(self) -> str:
        if not self.batch_automation_lock.acquire(blocking=False):
            raise RuntimeError("已有自动化批量任务正在运行，请等待完成后再启动新的自动化。")
        self.batch_automation_stop_requested = False
        return uuid.uuid4().hex

    def release_batch_automation(self) -> None:
        if self.batch_automation_lock.locked():
            self.batch_automation_lock.release()

    def create_batch_automation_task(
        self,
        request: BatchAutomationCreateDTO,
        automation_id: str,
        batch_index: int,
        attempt_index: int = 1,
    ) -> str:
        keyword_list = self.build_batch_task_keywords(request, attempt_index)
        task_request = TaskCreateDTO(
            source_type=request.source_type,
            industry=request.industry,
            keywords=keyword_list,
            target_city=request.target_city,
            collect_limit=request.batch_collect_limit,
            is_qcc_enabled=request.is_qcc_enabled,
            qcc_limit=min(request.qcc_limit, request.batch_collect_limit) if request.is_qcc_enabled else 0,
        )
        task_id = self.create_task(task_request)
        if batch_index <= request.batch_count:
            progress_text = f"第 {batch_index}/{request.batch_count} 轮"
        else:
            progress_text = f"补采尝试 {batch_index - request.batch_count}"
        keyword_preview = "、".join(keyword_list[:6])
        self.repository.insert_task_event(
            task_id,
            "info",
            (
                f"自动化批量任务 {automation_id[:8]}：{progress_text}，"
                f"目标新增 {request.batch_collect_limit} 条；本轮关键词：{keyword_preview}。"
            ),
        )
        return task_id

    def build_batch_task_keywords(self, request: BatchAutomationCreateDTO, attempt_index: int) -> List[str]:
        industry = self.normalize_industry(request.industry)
        base_keyword_list = self.normalize_keyword(request.keywords, industry, request.source_type)
        if request.source_type != SOURCE_TYPE_AI_WEB_SEARCH:
            return base_keyword_list
        seed_keyword_list = []
        for keyword in base_keyword_list:
            if keyword not in seed_keyword_list:
                seed_keyword_list.append(keyword)
        for keyword in BATCH_INDUSTRY_KEYWORD_EXPANSION_MAP.get(industry, []):
            if keyword not in seed_keyword_list:
                seed_keyword_list.append(keyword)
        if not seed_keyword_list:
            seed_keyword_list = [industry]

        city_rotation_list = self.get_batch_city_rotation_list(industry)
        offset = max(0, attempt_index - 1) * 3
        keyword_list = []
        for index in range(min(len(seed_keyword_list), 8)):
            seed_keyword = seed_keyword_list[(offset + index) % len(seed_keyword_list)]
            city = city_rotation_list[(offset + index) % len(city_rotation_list)]
            intent = BATCH_SEARCH_INTENT_LIST[(offset + index) % len(BATCH_SEARCH_INTENT_LIST)]
            candidate = self.build_batch_keyword(seed_keyword, city, intent)
            if candidate not in keyword_list:
                keyword_list.append(candidate)
        for keyword in base_keyword_list:
            if keyword not in keyword_list:
                keyword_list.append(keyword)
        return keyword_list[:10]

    def get_batch_city_rotation_list(self, industry: str) -> List[str]:
        city_list = BATCH_INDUSTRY_CITY_ROTATION_MAP.get(industry) or BATCH_CITY_ROTATION_LIST
        return city_list or BATCH_CITY_ROTATION_LIST

    def build_batch_keyword(self, seed_keyword: str, city: str, intent: str) -> str:
        keyword_part_list = []
        if not is_guangdong_text(seed_keyword):
            keyword_part_list.append(city)
        keyword_part_list.append(seed_keyword)
        if intent and intent not in seed_keyword:
            keyword_part_list.append(intent)
        return " ".join(part.strip() for part in keyword_part_list if part and part.strip())

    def run_reserved_batch_automation(
        self,
        automation_id: str,
        request: BatchAutomationCreateDTO,
        first_task_id: str,
    ) -> None:
        try:
            self.run_batch_automation(automation_id, request, first_task_id)
        finally:
            self.batch_automation_stop_requested = False
            self.release_batch_automation()

    def run_batch_automation(
        self,
        automation_id: str,
        request: BatchAutomationCreateDTO,
        first_task_id: str,
    ) -> None:
        task_id = first_task_id
        target_success_count = max(1, request.batch_count) * max(1, request.batch_collect_limit)
        accumulated_success_count = 0
        max_attempt_count = self.resolve_batch_max_attempt_count(request)
        attempt_index = 1
        while attempt_index <= max_attempt_count and accumulated_success_count < target_success_count:
            if self.batch_automation_stop_requested:
                break
            if attempt_index > 1:
                try:
                    task_id = self.create_batch_automation_task(
                        request,
                        automation_id,
                        attempt_index,
                        attempt_index,
                    )
                except Exception as ex:
                    logger.exception("Batch automation task create failed, automation_id=%s, error=%s", automation_id, ex)
                    break
                cooldown_seconds = self.resolve_batch_cooldown_seconds(request)
                if cooldown_seconds > 0:
                    wait_text = f"{cooldown_seconds:g}"
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        f"自动化批量任务：上一轮已结束，等待 {wait_text} 秒后启动本轮。",
                    )
                    time.sleep(cooldown_seconds)
                current_task = self.repository.get_task(task_id)
                if self.batch_automation_stop_requested or current_task is None or current_task["status"] != TASK_STATUS_PENDING:
                    break
            self.run_task(task_id)
            finished_task = self.repository.get_task(task_id)
            if finished_task is None:
                break
            current_success_count = int(finished_task.get("success_count") or 0)
            if request.source_type == SOURCE_TYPE_AI_WEB_SEARCH:
                visible_success_count = self.repository.count_lead_by_task_id(task_id)
                if visible_success_count != current_success_count:
                    current_success_count = visible_success_count
                    self.repository.update_task_status(
                        task_id,
                        finished_task["status"],
                        total_count=finished_task.get("total_count"),
                        success_count=visible_success_count,
                        failed_count=finished_task.get("failed_count"),
                    )
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        f"已按风险删除/重复合并后的真实入库数修正本轮新增：{visible_success_count} 条。",
                    )
            accumulated_success_count += current_success_count
            self.repository.insert_task_event(
                task_id,
                "info",
                (
                    f"自动化批量累计新增 {accumulated_success_count}/{target_success_count} 条；"
                    f"本次新增 {current_success_count} 条。"
                ),
            )
            if finished_task["status"] == TASK_STATUS_FAILED and request.source_type != SOURCE_TYPE_AI_WEB_SEARCH:
                self.repository.insert_task_event(
                    task_id,
                    "warning",
                    "本轮任务失败，自动化批量任务已停止，避免连续触发页面限制。",
                )
                break
            if current_success_count <= 0 and request.source_type == SOURCE_TYPE_AI_WEB_SEARCH:
                if attempt_index < max_attempt_count:
                    self.repository.insert_task_event(
                        task_id,
                        "warning",
                        "本次没有新增有效线索，系统会自动换一组长尾关键词补采；本次不代表目标线索已完成。",
                    )
                else:
                    self.repository.insert_task_event(
                        task_id,
                        "warning",
                        "自动化补采次数已达上限，仍未达到目标新增数量；建议缩小关键词到具体产品词或切换1688+天眼查链路。",
                    )
            if (
                accumulated_success_count < target_success_count
                and attempt_index < max_attempt_count
                and not self.batch_automation_stop_requested
            ):
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    "本次已完成，准备创建下一次自动化采集。",
                )
            attempt_index += 1

    def resolve_batch_max_attempt_count(self, request: BatchAutomationCreateDTO) -> int:
        if request.source_type != SOURCE_TYPE_AI_WEB_SEARCH:
            return request.batch_count
        return min(100, max(request.batch_count, request.batch_count * 3))

    def resolve_batch_cooldown_seconds(self, request: BatchAutomationCreateDTO) -> float:
        base_seconds = max(float(request.cooldown_seconds or 0), 0.0)
        if request.source_type in (SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_ALIBABA_INTERNATIONAL):
            base_seconds = max(base_seconds, 90.0)
        if base_seconds <= 0:
            return 0.0
        return round(base_seconds + random.uniform(0, base_seconds * 0.35), 1)

    def start_tianyancha_warmup(self) -> Dict:
        config = get_config()
        backend_dir = Path(__file__).resolve().parents[2]
        user_data_dir = config.qcc_public_web_user_data_dir.parent / "tianyancha"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        process_id_list = list_browser_profile_process_id(user_data_dir)
        if process_id_list:
            process_text = ", ".join(str(process_id) for process_id in process_id_list)
            raise RuntimeError(f"天眼查预热浏览器已打开，请先完成验证并关闭该浏览器。当前占用进程：{process_text}")

        stdout_path = config.log_dir / "tianyancha_warmup.out.log"
        stderr_path = config.log_dir / "tianyancha_warmup.err.log"
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
                        SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
                    ],
                    cwd=backend_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    creationflags=creation_flags,
                )
        except OSError as ex:
            raise RuntimeError(f"天眼查预热浏览器启动失败：{ex}") from ex
        return {
            "source_type": SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
            "process_id": process.pid,
            "warmup_url": "https://www.tianyancha.com/search?key=服装工厂",
            "message": "天眼查预热浏览器已打开；完成验证/登录后请关闭该浏览器，再启动采集任务。",
        }

    def start_alibaba_1688_warmup(self) -> Dict:
        config = get_config()
        backend_dir = Path(__file__).resolve().parents[2]
        user_data_dir = config.alibaba_1688_user_data_dir
        user_data_dir.mkdir(parents=True, exist_ok=True)
        process_id_list = list_browser_profile_process_id(user_data_dir)
        if process_id_list:
            process_text = ", ".join(str(process_id) for process_id in process_id_list)
            raise RuntimeError(f"1688预登录浏览器已打开，请先完成登录/验证并关闭该浏览器。当前占用进程：{process_text}")

        stdout_path = config.log_dir / "alibaba_1688_warmup.out.log"
        stderr_path = config.log_dir / "alibaba_1688_warmup.err.log"
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
                        SOURCE_TYPE_ALIBABA_1688,
                    ],
                    cwd=backend_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    creationflags=creation_flags,
                )
        except OSError as ex:
            raise RuntimeError(f"1688预登录浏览器启动失败：{ex}") from ex
        return {
            "source_type": SOURCE_TYPE_ALIBABA_1688,
            "process_id": process.pid,
            "warmup_url": "https://login.1688.com/member/signin.htm",
            "message": "1688预登录浏览器已打开；请在弹出的浏览器里完成登录/滑块验证，完成后关闭该浏览器，再启动采集任务。",
        }

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

    def assert_task_browser_profile_available(self, source_type: str) -> None:
        if source_type == SOURCE_TYPE_ALIBABA_1688:
            config = get_config()
            process_id_list = list_browser_profile_process_id(config.alibaba_1688_user_data_dir)
            if not process_id_list:
                return
            process_text = ", ".join(str(process_id) for process_id in process_id_list)
            raise RuntimeError(
                f"1688预登录浏览器还没有关闭，请先在弹出的1688浏览器里完成登录/验证，然后关闭该浏览器，再启动采集任务。当前占用进程：{process_text}"
            )
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
        if source_type != SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB:
            return
        config = get_config()
        user_data_dir = config.qcc_public_web_user_data_dir.parent / "tianyancha"
        process_id_list = list_browser_profile_process_id(user_data_dir)
        if not process_id_list:
            return
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(
            f"天眼查预热浏览器还没有关闭，请先在弹出的天眼查浏览器里完成验证/登录，然后关闭该浏览器，再启动采集任务。当前占用进程：{process_text}"
        )

    def create_task(self, request: TaskCreateDTO) -> str:
        task_id = uuid.uuid4().hex
        industry = self.normalize_industry(request.industry)
        keywords = self.normalize_keyword(request.keywords, industry, request.source_type)
        current_time = get_current_time_text()
        task_name = self.build_task_name(request.source_type, industry)
        target_city = self.normalize_target_city(request.source_type, request.target_city)
        is_qcc_enabled = request.is_qcc_enabled
        qcc_limit = request.qcc_limit
        if request.source_type in PUBLIC_WEB_ONLY_SOURCE_TYPE_SET:
            is_qcc_enabled = False
            qcc_limit = 0
        self.repository.insert_task(
            {
                "id": task_id,
                "task_name": task_name,
                "source_type": request.source_type,
                "industry": industry,
                "keyword_text": ",".join(keywords),
                "target_city": target_city,
                "collect_limit": request.collect_limit,
                "is_qcc_enabled": 1 if is_qcc_enabled else 0,
                "qcc_limit": qcc_limit,
                "status": TASK_STATUS_PENDING,
                "gmt_create": current_time,
                "gmt_modified": current_time,
            }
        )
        self.repository.insert_task_event(task_id, "info", "任务已创建，等待执行")
        return task_id

    def create_ai_lead_discovery_task(self, request: TaskCreateDTO) -> str:
        industry = self.normalize_industry(request.industry)
        base_keyword_list = self.normalize_keyword(request.keywords, industry, request.source_type)
        keyword_list = list(base_keyword_list)
        ai_reason = ""
        if industry == INDUSTRY_OTHER:
            ai_reason = "其他类目采用提示词精准模式，未使用AI扩写关键词。"
        elif self.deepseek_ai_service.is_enabled():
            try:
                ai_result = self.deepseek_ai_service.build_lead_discovery_keywords(
                    industry=industry,
                    source_type=request.source_type,
                    raw_keyword_list=base_keyword_list,
                    collect_limit=request.collect_limit,
                )
                if ai_result["keywords"]:
                    keyword_list = ai_result["keywords"]
                    ai_reason = ai_result.get("reason", "")
            except Exception as ex:
                logger.exception("AI lead discovery keyword generation failed, error=%s", ex)
                ai_reason = f"DeepSeek关键词生成失败，已使用原关键词；原因：{ex}"
        else:
            ai_reason = "DeepSeek未启用或未配置Key，已使用原关键词。"

        ai_request = TaskCreateDTO(
            source_type=request.source_type,
            industry=industry,
            keywords=keyword_list,
            target_city=request.target_city,
            collect_limit=request.collect_limit,
            is_qcc_enabled=request.is_qcc_enabled,
            qcc_limit=request.qcc_limit,
        )
        task_id = self.create_task(ai_request)
        keyword_preview = "，".join(keyword_list[:10])
        self.repository.insert_task_event(
            task_id,
            "info",
            f"AI智能线索发现已创建：关键词：{keyword_preview}。{ai_reason}",
        )
        return task_id

    def build_tianyancha_enrichment_pacing_profile(self, pacing_mode: str) -> Dict:
        clean_mode = str(pacing_mode or "").strip().lower()
        profile = TIANYANCHA_ENRICHMENT_PACING_PROFILE_MAP.get(
            clean_mode,
            TIANYANCHA_ENRICHMENT_PACING_PROFILE_MAP["conservative"],
        )
        return dict(profile)

    def create_tianyancha_enrichment_task(self, request: TianyanchaEnrichmentCreateDTO) -> str:
        task_id = uuid.uuid4().hex
        current_time = get_current_time_text()
        source_task_id = (request.task_id or "").strip()
        if source_task_id:
            source_task = self.repository.get_task(source_task_id)
            if source_task is None:
                raise RuntimeError("未找到要补全的1688任务，请先刷新任务列表后重试")
            if source_task.get("source_type") != SOURCE_TYPE_ALIBABA_1688:
                raise RuntimeError("只能选择1688采集任务进行天眼查补全")
        self.repository.insert_task(
            {
                "id": task_id,
                "task_name": "天眼查手动补全 1688已存线索",
                "source_type": SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
                "industry": "1688补全",
                "keyword_text": "1688已存线索",
                "collect_limit": request.limit,
                "is_qcc_enabled": 0,
                "qcc_limit": 0,
                "status": TASK_STATUS_PENDING,
                "gmt_create": current_time,
                "gmt_modified": current_time,
            }
        )
        self.repository.insert_task_event(
            task_id,
            "info",
            f"天眼查手动补全任务已创建，本次最多补全 {request.limit} 条1688已存线索",
        )
        return task_id

    def create_qixin_enrichment_task(self, request: QixinEnrichmentCreateDTO) -> str:
        self.qixin_api_service.assert_configured()
        task_id = uuid.uuid4().hex
        current_time = get_current_time_text()
        source_task_id = (request.task_id or "").strip()
        if source_task_id:
            source_task = self.repository.get_task(source_task_id)
            if source_task is None:
                raise RuntimeError("未找到要补全的1688任务，请先刷新任务列表后重试")
            if source_task.get("source_type") != SOURCE_TYPE_ALIBABA_1688:
                raise RuntimeError("只能选择1688采集任务进行启信宝补全")
        self.repository.insert_task(
            {
                "id": task_id,
                "task_name": "启信宝API补全 1688已存线索",
                "source_type": SOURCE_TYPE_QIXIN_PUBLIC_WEB,
                "industry": "1688补全",
                "keyword_text": "1688已存线索",
                "collect_limit": request.limit,
                "is_qcc_enabled": 0,
                "qcc_limit": 0,
                "status": TASK_STATUS_PENDING,
                "gmt_create": current_time,
                "gmt_modified": current_time,
            }
        )
        self.repository.insert_task_event(
            task_id,
            "info",
            f"启信宝API补全任务已创建，本次最多补全 {request.limit} 条1688已存线索",
        )
        return task_id

    def run_qixin_enrichment_task(self, task_id: str, source_task_id: str = "") -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            logger.warning("Qixin enrichment task not found, task_id=%s", task_id)
            return
        candidate_list = []
        success_count = 0
        failed_count = 0
        try:
            self.repository.update_task_status(task_id, TASK_STATUS_RUNNING)
            candidate_list = self.repository.list_alibaba_1688_tianyancha_enrichment_candidate(
                int(task.get("collect_limit") or 20),
                task_id=(source_task_id or "").strip(),
            )
            self.repository.update_task_status(
                task_id,
                TASK_STATUS_COLLECTING,
                total_count=len(candidate_list),
                success_count=0,
                failed_count=0,
            )
            if not candidate_list:
                self.finalize_task_status(
                    task_id=task_id,
                    total_count=0,
                    success_count=0,
                    failed_count=0,
                    success_message="没有找到需要启信宝补全的1688已存线索",
                )
                return

            self.repository.insert_task_event(
                task_id,
                "info",
                f"开始启信宝API补全：共 {len(candidate_list)} 条；每条成功后立即保存，单条失败不回滚已完成数据",
            )
            for index, candidate in enumerate(candidate_list, start=1):
                current_task = self.repository.get_task(task_id)
                if current_task is None or current_task.get("status") not in {
                    TASK_STATUS_RUNNING,
                    TASK_STATUS_COLLECTING,
                    TASK_STATUS_SAVING,
                }:
                    self.repository.insert_task_event(task_id, "warning", "启信宝补全已停止，已完成数据保持不变")
                    return
                company_name = candidate["enrichment_company_name"]
                try:
                    result = self.qixin_api_service.query_company(
                        company_name,
                        candidate.get("industry") or "",
                    )
                    self.update_alibaba_1688_lead_with_tianyancha(candidate, result.lead)
                    success_count += 1
                    endpoint_text = "，".join(
                        f"{name}:{'成功' if status.get('success') else status.get('message') or '失败'}"
                        for name, status in result.endpoint_status.items()
                    )
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        f"启信宝补全 {index}/{len(candidate_list)} 成功：{company_name}；{endpoint_text}",
                    )
                except QixinApiError as ex:
                    failed_count += 1
                    self.repository.insert_task_event(
                        task_id,
                        "warning",
                        f"启信宝补全 {index}/{len(candidate_list)} 未完成：{company_name}；{ex}",
                    )
                    if ex.is_authorization_denied():
                        failed_count += max(0, len(candidate_list) - index)
                        connection_status = self.qixin_api_service.get_connection_status()
                        egress_ip = str(connection_status.get("egress_ip") or "未知")
                        self.repository.update_task_status(
                            task_id,
                            TASK_STATUS_FAILED,
                            total_count=len(candidate_list),
                            success_count=success_count,
                            failed_count=failed_count,
                        )
                        self.repository.insert_task_event(
                            task_id,
                            "error",
                            (
                                f"启信宝授权失败，已停止后续API调用；当前出口IP：{egress_ip}。"
                                "请将该IP加入启信宝API白名单后重新补全，已成功数据保持不变。"
                            ),
                        )
                        return
                self.repository.update_task_status(
                    task_id,
                    TASK_STATUS_SAVING,
                    total_count=len(candidate_list),
                    success_count=success_count,
                    failed_count=failed_count,
                )
            self.finalize_task_status(
                task_id=task_id,
                total_count=len(candidate_list),
                success_count=success_count,
                failed_count=failed_count,
                success_message=f"启信宝API补全完成：成功 {success_count} 条，未完成 {failed_count} 条",
            )
        except Exception as ex:
            remaining_failed_count = max(0, len(candidate_list) - success_count - failed_count)
            failed_count += remaining_failed_count
            self.repository.update_task_status(
                task_id,
                TASK_STATUS_FAILED,
                total_count=len(candidate_list),
                success_count=success_count,
                failed_count=failed_count,
            )
            self.repository.insert_task_event(
                task_id,
                "error",
                f"启信宝API补全失败：已保存 {success_count} 条，剩余 {failed_count} 条未完成；原因：{ex}",
            )
            logger.exception("Qixin enrichment task failed, task_id=%s, error=%s", task_id, ex)

    def run_tianyancha_enrichment_task(self, task_id: str, source_task_id: str = "", pacing_mode: str = "conservative") -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            logger.warning("Tianyancha enrichment task not found, task_id=%s", task_id)
            return
        candidate_list = []
        success_count = 0
        failed_count = 0
        phone_enriched_count = 0
        contact_enriched_count = 0
        try:
            self.repository.update_task_status(task_id, TASK_STATUS_RUNNING)
            candidate_list = self.repository.list_alibaba_1688_tianyancha_enrichment_candidate(
                int(task.get("collect_limit") or 20),
                task_id=(source_task_id or "").strip(),
            )
            self.repository.update_task_status(
                task_id,
                TASK_STATUS_COLLECTING,
                total_count=len(candidate_list),
                success_count=0,
                failed_count=0,
            )
            if not candidate_list:
                self.finalize_task_status(
                    task_id=task_id,
                    total_count=0,
                    success_count=0,
                    failed_count=0,
                    success_message="没有找到需要补全的1688已存线索",
                )
                return

            collector = self.collector_factory.get_collector(SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB)
            self.bind_collector_task_event_callback(collector, task_id)
            company_name_list = [candidate["enrichment_company_name"] for candidate in candidate_list]
            industry = self.pick_tianyancha_enrichment_industry(candidate_list)
            pacing_profile = self.build_tianyancha_enrichment_pacing_profile(pacing_mode)
            batch_size = max(1, int(pacing_profile["batch_size"]))
            cooldown_seconds = max(0.0, float(pacing_profile["cooldown_seconds"]))
            self.repository.insert_task_event(
                task_id,
                "info",
                f"开始按企业名补全天眼查信息：本次 {len(company_name_list)} 条；如触发风控，可先停止任务，1688基础线索不会丢失",
            )
            self.repository.insert_task_event(
                task_id,
                "info",
                (
                    f"天眼查补全节奏：{pacing_profile['label']}，"
                    f"每批 {batch_size} 条，批间冷却 {int(cooldown_seconds)} 秒"
                ),
            )
            success_count = 0
            failed_count = 0
            phone_enriched_count = 0
            contact_enriched_count = 0
            for batch_start in range(0, len(company_name_list), batch_size):
                batch_index = batch_start // batch_size + 1
                batch_company_name_list = company_name_list[batch_start : batch_start + batch_size]
                batch_candidate_list = candidate_list[batch_start : batch_start + batch_size]
                if batch_start > 0 and cooldown_seconds > 0:
                    wait_seconds = round(cooldown_seconds + random.uniform(0, min(30.0, cooldown_seconds * 0.2)), 1)
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        f"天眼查补全进入批间冷却：等待 {wait_seconds} 秒后继续第 {batch_index} 批",
                    )
                    time.sleep(wait_seconds)
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    f"天眼查补全第 {batch_index} 批启动：{len(batch_company_name_list)} 条",
                )
                batch_enriched_lead_list = collector.collect_by_company_names(
                    industry=industry,
                    company_name_list=batch_company_name_list,
                    collect_limit=len(batch_company_name_list),
                )
                batch_enrichment_map = self.build_tianyancha_enrichment_map(batch_enriched_lead_list)
                for candidate in batch_candidate_list:
                    enrichment = self.find_tianyancha_enrichment(
                        candidate["enrichment_company_name"],
                        batch_enrichment_map,
                    )
                    if enrichment is None:
                        failed_count += 1
                        self.repository.update_task_status(
                            task_id,
                            TASK_STATUS_SAVING,
                            total_count=len(candidate_list),
                            success_count=success_count,
                            failed_count=failed_count,
                        )
                        continue
                    before_record = self.repository.get_lead_by_id(candidate["id"])
                    self.update_alibaba_1688_lead_with_tianyancha(candidate, enrichment)
                    after_record = self.repository.get_lead_by_id(candidate["id"])
                    success_count += 1
                    if self.has_phone_enriched(before_record.get("phone", ""), after_record.get("phone", "")):
                        phone_enriched_count += 1
                    if self.has_contact_enriched(before_record, after_record):
                        contact_enriched_count += 1
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_SAVING,
                        total_count=len(candidate_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
            self.repository.insert_task_event(
                task_id,
                "info",
                (
                    f"天眼查手动补全完成：匹配更新 {success_count} 条，"
                    f"补到电话 {phone_enriched_count} 条，补到联系人/法人 {contact_enriched_count} 条"
                ),
            )
            self.finalize_task_status(
                task_id=task_id,
                total_count=len(candidate_list),
                success_count=success_count,
                failed_count=failed_count,
                success_message="天眼查手动补全任务完成",
            )
        except Exception as ex:
            remaining_failed_count = max(0, len(candidate_list) - success_count - failed_count)
            failed_count += remaining_failed_count
            if candidate_list:
                self.repository.update_task_status(
                    task_id,
                    TASK_STATUS_FAILED,
                    total_count=len(candidate_list),
                    success_count=success_count,
                    failed_count=failed_count,
                )
            else:
                self.repository.update_task_status(task_id, TASK_STATUS_FAILED)
            self.repository.insert_task_event(
                task_id,
                "error",
                f"天眼查手动补全失败：已保存 {success_count} 条，剩余 {failed_count} 条未完成；原因：{ex}",
            )
            logger.exception("Tianyancha enrichment task failed, task_id=%s, error=%s", task_id, ex)
            return
            self.repository.update_task_status(task_id, TASK_STATUS_FAILED)
            self.repository.insert_task_event(task_id, "error", f"天眼查手动补全失败：{ex}")
            logger.exception("Tianyancha enrichment task failed, task_id=%s, error=%s", task_id, ex)

    def pick_tianyancha_enrichment_industry(self, candidate_list: List[Dict]) -> str:
        for candidate in candidate_list:
            industry = str(candidate.get("industry") or "").strip()
            if industry:
                return industry
        return "服装"

    def build_tianyancha_enrichment_map(self, lead_list: List[CollectedLeadDTO]) -> Dict[str, CollectedLeadDTO]:
        result = {}
        for lead in lead_list:
            key = EnterprisePublicWebCollector.normalize_company_match_key(lead.suspected_company_name)
            if key and key not in result:
                result[key] = lead
        return result

    def find_tianyancha_enrichment(
        self,
        company_name: str,
        enrichment_map: Dict[str, CollectedLeadDTO],
    ) -> Optional[CollectedLeadDTO]:
        key = EnterprisePublicWebCollector.normalize_company_match_key(company_name)
        return enrichment_map.get(key)

    def update_alibaba_1688_lead_with_tianyancha(self, candidate: Dict, enrichment: CollectedLeadDTO) -> None:
        enrichment.source_type = SOURCE_TYPE_ALIBABA_1688
        enrichment.source_keyword = candidate.get("source_keyword") or enrichment.source_keyword
        enrichment.industry = candidate.get("industry") or enrichment.industry
        enrichment.product_name = candidate.get("product_name") or ""
        company_verify = self.build_public_web_verify(enrichment)
        score_result = self.scoring_service.calculate_score(enrichment, company_verify)
        lead_data = self.build_lead_data(
            candidate.get("task_id") or "",
            enrichment,
            company_verify,
            score_result,
        )
        candidate_shop_url = str(candidate.get("shop_url") or "").strip()
        candidate_profile_url = str(candidate.get("profile_url") or "").strip()
        lead_data["product_name"] = str(candidate.get("product_name") or "").strip()
        lead_data["shop_url"] = candidate_shop_url
        lead_data["profile_url"] = candidate_profile_url or candidate_shop_url
        self.repository.update_lead_public_fields(candidate["id"], lead_data)

    def run_task(self, task_id: str) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            logger.warning("Task not found, task_id=%s", task_id)
            return
        try:
            self.repository.update_task_status(task_id, TASK_STATUS_RUNNING)
            self.repository.insert_task_event(task_id, "info", "任务启动，准备读取任务参数")
            keywords = self.split_keyword_text(task["keyword_text"])
            collector = self.collector_factory.get_collector(task["source_type"])
            self.bind_collector_task_event_callback(collector, task_id)
            self.bind_collector_existing_lead_identity(collector, task["source_type"])
            self.repository.update_task_status(task_id, TASK_STATUS_COLLECTING)
            self.repository.insert_task_event(task_id, "info", "正在采集公开页面线索")
            if task["source_type"] == SOURCE_TYPE_ALIBABA_1688:
                keyword_preview = "、".join(keywords[:5]) if keywords else task["industry"]
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    f"1688采集已启动：搜索词：{keyword_preview}；系统只采集并保存1688企业线索，不会自动跳转天眼查。需要补全联系人、法人和电话时，请在任务完成后手动点击天眼查补全。",
                )
            if task["source_type"] == SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    "1688页面助手已打开；请在浏览器中停留到目标列表页，系统将在约60秒后提取当前页可见字段",
                )
            if task["source_type"] == SOURCE_TYPE_QCC_PUBLIC_WEB:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    "企查查公开页采集已启动；如浏览器出现登录或验证，请人工完成后保持页面打开，系统会自动继续。",
                )
            if task["source_type"] == SOURCE_TYPE_FENGNIAO_PUBLIC_WEB:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    "美亚风鸟已启动；如浏览器出现登录或验证，请人工完成后保持页面打开，系统会自动继续。",
                )
            if task["source_type"] in (
                SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
                SOURCE_TYPE_QIXIN_PUBLIC_WEB,
                SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
            ):
                source_name = PUBLIC_ENTERPRISE_SOURCE_NAME_MAP[task["source_type"]]
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    f"{source_name}公开页采集已启动；仅读取公开可见字段。如出现登录或验证，请人工完成后保持页面打开，系统会自动继续。",
                )
            if task["source_type"] == SOURCE_TYPE_AI_WEB_SEARCH:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    "AI 1688搜企已启动：系统只查询搜索引擎已收录的1688公开摘要，不自动进入1688页面；候选先入库，任务最后再用天眼查补全联系人、法人和电话。",
                )
            if task["source_type"] == SOURCE_TYPE_DOUYIN_QCC:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    "抖音公开线索采集已启动；仅读取公开可见字段。若抖音或企查查出现登录/验证，请人工完成后保持页面打开。",
                )
            collect_kwargs = {
                "industry": task["industry"],
                "keywords": keywords,
                "collect_limit": task["collect_limit"],
            }
            if task["source_type"] in TARGET_CITY_SOURCE_TYPE_SET:
                collect_kwargs["target_city"] = task.get("target_city") or "广东省"
            collected_lead_list = collector.collect(**collect_kwargs)
            self.repository.update_task_status(
                task_id,
                TASK_STATUS_VERIFYING if task["is_qcc_enabled"] == 1 else TASK_STATUS_SCORING,
                total_count=len(collected_lead_list),
            )
            self.insert_after_collect_event(task_id, task, len(collected_lead_list), collector)
            success_count = 0
            failed_count = 0
            merged_count = 0
            qcc_used_count = 0
            is_quota_warning_emitted = False
            is_scoring_event_emitted = False
            is_saving_event_emitted = False
            for collected_lead in collected_lead_list:
                try:
                    if task["is_qcc_enabled"] == 1:
                        self.repository.update_task_status(
                            task_id,
                            TASK_STATUS_VERIFYING,
                            total_count=len(collected_lead_list),
                            success_count=success_count,
                            failed_count=failed_count,
                        )
                    company_verify = self.verify_company_if_needed(task, collected_lead, qcc_used_count)
                    if (
                        company_verify.verification_status == VERIFY_STATUS_QUOTA_LIMITED
                        and not is_quota_warning_emitted
                    ):
                        self.repository.insert_task_event(task_id, "warning", "企查查本地额度不足，后续线索将跳过核验")
                        is_quota_warning_emitted = True
                    if company_verify.consume_count > 0:
                        qcc_used_count += company_verify.consume_count
                    disqualified_reason = self.get_disqualified_reason(collected_lead, company_verify)
                    if disqualified_reason:
                        failed_count += 1
                        self.repository.insert_task_event(
                            task_id,
                            "info",
                            f"已跳过非正常状态线索：{collected_lead.suspected_company_name}，原因：{disqualified_reason}",
                        )
                        self.repository.update_task_status(
                            task_id,
                            TASK_STATUS_VERIFYING if task["is_qcc_enabled"] == 1 else TASK_STATUS_SCORING,
                            total_count=len(collected_lead_list),
                            success_count=success_count,
                            failed_count=failed_count,
                        )
                        continue
                    target_region_disqualified_reason = self.get_target_region_disqualified_reason(
                        task,
                        collected_lead,
                        company_verify,
                    )
                    if target_region_disqualified_reason:
                        failed_count += 1
                        self.repository.insert_task_event(
                            task_id,
                            "info",
                            (
                                f"已跳过地区不符线索：{collected_lead.suspected_company_name}，"
                                f"原因：{target_region_disqualified_reason}"
                            ),
                        )
                        self.repository.update_task_status(
                            task_id,
                            TASK_STATUS_VERIFYING if task["is_qcc_enabled"] == 1 else TASK_STATUS_SCORING,
                            total_count=len(collected_lead_list),
                            success_count=success_count,
                            failed_count=failed_count,
                        )
                        continue
                    if not is_scoring_event_emitted:
                        self.repository.insert_task_event(task_id, "info", "正在进行线索评分与分级")
                        is_scoring_event_emitted = True
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_SCORING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                    score_result = self.scoring_service.calculate_score(collected_lead, company_verify)
                    if not is_saving_event_emitted:
                        self.repository.insert_task_event(task_id, "info", "正在写入线索库并更新任务进度")
                        is_saving_event_emitted = True
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_SAVING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                    is_inserted = self.save_lead_once(task_id, collected_lead, company_verify, score_result)
                    if company_verify.consume_count > 0:
                        self.insert_usage_log(task_id, company_verify)
                    if not is_inserted:
                        merged_count += 1
                        self.repository.insert_task_event(
                            task_id,
                            "info",
                            f"已合并重复线索：{collected_lead.suspected_company_name}",
                        )
                        self.repository.update_task_status(
                            task_id,
                            TASK_STATUS_SAVING,
                            total_count=len(collected_lead_list),
                            success_count=success_count,
                            failed_count=failed_count,
                        )
                        continue
                    success_count += 1
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_SAVING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                except Exception as ex:
                    failed_count += 1
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_SAVING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                    logger.exception("Lead processing failed, task_id=%s, error=%s", task_id, ex)
            if task["source_type"] in (SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB, SOURCE_TYPE_AI_WEB_SEARCH) and collected_lead_list:
                self.enrich_tianyancha_saved_leads_at_end(task_id, task, collector, collected_lead_list)
            removed_missing_phone_count = self.cleanup_unassigned_leads_without_public_phone(
                task_id,
                task["source_type"],
            )
            if removed_missing_phone_count:
                failed_count += removed_missing_phone_count
            if task["source_type"] in PHONE_REQUIRED_SOURCE_TYPE_SET:
                actual_success_count = self.repository.count_lead_by_task_id(task_id)
                if actual_success_count != success_count:
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        (
                            f"本轮入库数量已按真实线索库记录修正：新增 {actual_success_count} 条；"
                            f"采集候选 {len(collected_lead_list)} 条，重复合并 {merged_count} 条，过滤/删除 {failed_count} 条。"
                        ),
                    )
                    success_count = actual_success_count
            elif merged_count > 0:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    f"本轮采集候选 {len(collected_lead_list)} 条，新增 {success_count} 条，重复合并 {merged_count} 条。",
                )
            self.finalize_task_status(
                task_id=task_id,
                total_count=len(collected_lead_list),
                success_count=success_count,
                failed_count=failed_count,
                success_message="任务执行完成",
            )
        except Exception as ex:
            self.repository.update_task_status(task_id, TASK_STATUS_FAILED)
            if self.is_browser_closed_error(ex):
                self.repository.insert_task_event(
                    task_id,
                    "warning",
                    "采集浏览器已关闭或任务被手动停止，后台等待页面时中断；请确认页面仍打开后重新启动任务",
                )
            else:
                self.repository.insert_task_event(task_id, "error", f"任务失败：{ex}")
            logger.exception("Task failed, task_id=%s, error=%s", task_id, ex)

    def enrich_tianyancha_saved_leads_at_end(
        self,
        task_id: str,
        task,
        collector,
        collected_lead_list,
    ) -> None:
        company_name_list = []
        for lead in collected_lead_list:
            company_name = (lead.suspected_company_name or "").strip()
            if company_name and company_name not in company_name_list:
                company_name_list.append(company_name)
        if not company_name_list or not hasattr(collector, "collect_by_company_names"):
            return
        self.repository.insert_task_event(
            task_id,
            "info",
            f"基础线索已先入库，开始最后补全天眼查电话、联系人和法人；如出现身份验证，已入库数据不会丢失。",
        )
        try:
            enriched_lead_list = collector.collect_by_company_names(
                industry=task["industry"],
                company_name_list=company_name_list,
                collect_limit=len(company_name_list),
            )
        except Exception as ex:
            self.repository.insert_task_event(
                task_id,
                "warning",
                f"最后补全天眼查详情失败，已保留基础入库线索；原因：{ex}",
            )
            logger.exception("Tianyancha final enrichment failed, task_id=%s, error=%s", task_id, ex)
            return
        updated_count = 0
        phone_enriched_count = 0
        contact_enriched_count = 0
        for enriched_lead in enriched_lead_list:
            enriched_lead.source_type = task["source_type"]
            enriched_lead.source_keyword = task.get("keyword_text", "") or enriched_lead.source_keyword
            update_result = self.update_existing_public_web_lead(task_id, enriched_lead)
            if update_result["updated"]:
                updated_count += 1
            if update_result["phone_enriched"]:
                phone_enriched_count += 1
            if update_result["contact_enriched"]:
                contact_enriched_count += 1
        self.repository.insert_task_event(
            task_id,
            "info",
            (
                f"天眼查最后补全完成：匹配/更新 {updated_count} 条已入库线索，"
                f"补到或追加电话 {phone_enriched_count} 条，补到联系人/法人 {contact_enriched_count} 条。"
            ),
        )

    def cleanup_unassigned_leads_without_public_phone(self, task_id: str, source_type: str) -> int:
        if source_type not in PHONE_REQUIRED_SOURCE_TYPE_SET:
            return 0
        removed_count = self.repository.delete_unassigned_lead_without_public_phone(task_id)
        if removed_count <= 0:
            return 0
        self.repository.insert_task_event(
            task_id,
            "warning",
            (
                f"已自动剔除 {removed_count} 条未补到公开电话的未分配线索；"
                "这些线索不计入有效成功数，避免线索库保留“未公开”电话。"
            ),
        )
        return removed_count

    def update_existing_public_web_lead(self, task_id: str, collected_lead) -> Dict:
        company_verify = self.build_public_web_verify(collected_lead)
        score_result = self.scoring_service.calculate_score(collected_lead, company_verify)
        lead_data = self.build_lead_data(task_id, collected_lead, company_verify, score_result)
        duplicate_lead_id = self.repository.find_duplicate_lead_id(lead_data)
        if not duplicate_lead_id:
            return {"updated": False, "phone_enriched": False, "contact_enriched": False}
        before_record = self.repository.get_lead_by_id(duplicate_lead_id)
        disqualified_reason = self.get_disqualified_reason(collected_lead, company_verify)
        if disqualified_reason:
            deleted_count = self.repository.delete_lead_by_id(duplicate_lead_id)
            if deleted_count > 0:
                self.repository.insert_task_event(
                    task_id,
                    "info",
                    f"已删除非正常状态线索：{collected_lead.suspected_company_name}，原因：{disqualified_reason}",
                )
            return {"updated": False, "phone_enriched": False, "contact_enriched": False}
        self.repository.update_lead_public_fields(duplicate_lead_id, lead_data)
        after_record = self.repository.get_lead_by_id(duplicate_lead_id)
        return {
            "updated": True,
            "phone_enriched": self.has_phone_enriched(before_record.get("phone", ""), after_record.get("phone", "")),
            "contact_enriched": self.has_contact_enriched(before_record, after_record),
        }

    def has_phone_enriched(self, before_phone: str, after_phone: str) -> bool:
        before_phone_set = self.split_visible_phone_set(before_phone)
        after_phone_set = self.split_visible_phone_set(after_phone)
        return bool(after_phone_set - before_phone_set)

    def split_visible_phone_set(self, phone_text: str) -> set:
        phone_set = set()
        for phone in re.split(r"[；;,，\s]+", phone_text or ""):
            digit_text = re.sub(r"\D+", "", phone)
            if len(digit_text) >= 7:
                phone_set.add(digit_text)
        return phone_set

    def has_contact_enriched(self, before_record: Dict, after_record: Dict) -> bool:
        before_contact = self.pick_visible_contact_text(before_record)
        after_contact = self.pick_visible_contact_text(after_record)
        return bool(after_contact and after_contact != before_contact)

    def pick_visible_contact_text(self, record: Dict) -> str:
        for field_name in ("contact_name", "legal_person"):
            value = str(record.get(field_name) or "").strip()
            if value and value not in ("未公开", "号码皆未公开", "-"):
                return value
        return ""

    def import_1688_snapshot(self, request: Alibaba1688SnapshotDTO) -> Dict:
        task_id = uuid.uuid4().hex
        industry = self.normalize_industry(request.industry)
        keyword = request.source_keyword.strip() or "1688当前页面"
        current_time = get_current_time_text()
        task_data = {
            "id": task_id,
            "task_name": self.build_task_name(SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT, industry),
            "source_type": SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
            "industry": industry,
            "keyword_text": keyword,
            "collect_limit": request.collect_limit,
            "is_qcc_enabled": 1 if request.is_qcc_enabled else 0,
            "qcc_limit": request.qcc_limit,
            "status": TASK_STATUS_RUNNING,
            "total_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "gmt_create": current_time,
            "gmt_modified": current_time,
        }
        self.repository.insert_task(task_data)
        self.repository.insert_task_event(task_id, "info", "已接收1688普通页面公开内容，开始解析")
        try:
            parser = Alibaba1688SnapshotParser()
            self.repository.update_task_status(task_id, TASK_STATUS_COLLECTING)
            card_dump_list = [card.model_dump() for card in request.cards]
            collected_lead_list = parser.parse_snapshot(
                industry=industry,
                source_keyword=keyword,
                page_url=request.page_url,
                page_title=request.page_title,
                page_text=request.page_text,
                card_list=card_dump_list,
                collect_limit=request.collect_limit,
            )
            collected_lead_list = self.merge_1688_snapshot_ai_lead_list(
                task_id=task_id,
                industry=industry,
                source_keyword=keyword,
                page_url=request.page_url,
                page_title=request.page_title,
                page_text=request.page_text,
                card_list=card_dump_list,
                collect_limit=request.collect_limit,
                collected_lead_list=collected_lead_list,
            )
            self.repository.update_task_status(
                task_id,
                TASK_STATUS_VERIFYING if task_data["is_qcc_enabled"] == 1 else TASK_STATUS_SCORING,
                total_count=len(collected_lead_list),
            )
            self.insert_after_collect_event(task_id, task_data, len(collected_lead_list))
            success_count, failed_count = self.save_collected_lead_list(task_id, task_data, collected_lead_list)
            self.finalize_task_status(
                task_id=task_id,
                total_count=len(collected_lead_list),
                success_count=success_count,
                failed_count=failed_count,
                success_message="1688普通页面导入完成",
            )
            return {
                "task_id": task_id,
                "lead_count": success_count,
                "parsed_count": len(collected_lead_list),
                "failed_count": failed_count,
            }
        except Exception as ex:
            self.repository.update_task_status(task_id, TASK_STATUS_FAILED)
            self.repository.insert_task_event(task_id, "error", f"任务失败：{ex}")
            logger.exception("1688 snapshot import failed, task_id=%s, error=%s", task_id, ex)
            raise

    def merge_1688_snapshot_ai_lead_list(
        self,
        task_id: str,
        industry: str,
        source_keyword: str,
        page_url: str,
        page_title: str,
        page_text: str,
        card_list: List[Dict],
        collect_limit: int,
        collected_lead_list: List[CollectedLeadDTO],
    ) -> List[CollectedLeadDTO]:
        if not self.deepseek_ai_service.is_enabled():
            return collected_lead_list
        self.repository.insert_task_event(task_id, "info", "DeepSeek AI智能识别已开启，正在辅助识别1688页面字段")
        try:
            ai_result = self.deepseek_ai_service.analyze_1688_snapshot(
                industry=industry,
                source_keyword=source_keyword,
                page_url=page_url,
                page_title=page_title,
                page_text=page_text,
                card_list=card_list,
                collect_limit=collect_limit,
                source_type=SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
            )
        except Exception as ex:
            logger.exception("DeepSeek 1688 snapshot recognition failed, task_id=%s, error=%s", task_id, ex)
            self.repository.insert_task_event(task_id, "warning", f"DeepSeek AI识别失败，继续使用规则解析结果；原因：{ex}")
            return collected_lead_list

        if ai_result.page_state in ("login_required", "verification_required"):
            self.repository.insert_task_event(
                task_id,
                "warning",
                f"DeepSeek AI判断当前页面需要登录或验证：{ai_result.reason or ai_result.page_state}；系统不会绕过验证，请人工处理后重新导入或采集。",
            )
        elif ai_result.page_state and ai_result.page_state != "normal":
            self.repository.insert_task_event(
                task_id,
                "info",
                f"DeepSeek AI页面状态：{ai_result.page_state}；{ai_result.reason}",
            )

        merged_lead_list = list(collected_lead_list)
        added_count = 0
        enriched_count = 0
        for ai_lead in ai_result.lead_list:
            merge_key = self.build_ai_merge_key(ai_lead)
            if not merge_key:
                continue
            existing_lead = next((lead for lead in merged_lead_list if self.build_ai_merge_key(lead) == merge_key), None)
            if existing_lead is not None:
                if self.enrich_lead_from_ai(existing_lead, ai_lead):
                    enriched_count += 1
                continue
            if len(merged_lead_list) >= collect_limit:
                continue
            merged_lead_list.append(ai_lead)
            added_count += 1

        self.repository.insert_task_event(
            task_id,
            "info",
            f"DeepSeek AI识别完成：新增 {added_count} 条，补充字段 {enriched_count} 条，页面状态 {ai_result.page_state}。",
        )
        return merged_lead_list

    def build_ai_merge_key(self, lead: CollectedLeadDTO) -> str:
        return re.sub(r"\s+", "", lead.suspected_company_name or "")

    def enrich_lead_from_ai(self, target: CollectedLeadDTO, source: CollectedLeadDTO) -> bool:
        changed = False
        for field_name in (
            "product_name",
            "contact_name",
            "phone",
            "phone_source",
            "business_scope",
            "registered_address",
            "risk_tag",
            "region_text",
            "shop_url",
            "profile_url",
        ):
            if getattr(target, field_name) or not getattr(source, field_name):
                continue
            setattr(target, field_name, getattr(source, field_name))
            changed = True
        target.is_enterprise_verified = target.is_enterprise_verified or source.is_enterprise_verified
        target.commercial_keyword_count = max(target.commercial_keyword_count, source.commercial_keyword_count)
        return changed

    def finalize_task_status(
        self,
        task_id: str,
        total_count: int,
        success_count: int,
        failed_count: int,
        success_message: str,
    ) -> None:
        if success_count > 0:
            self.repository.update_task_status(
                task_id,
                TASK_STATUS_COMPLETED,
                total_count=total_count,
                success_count=success_count,
                failed_count=failed_count,
            )
            self.repository.insert_task_event(task_id, "info", success_message)
            return
        self.repository.update_task_status(
            task_id,
            TASK_STATUS_FAILED,
            total_count=total_count,
            success_count=success_count,
            failed_count=failed_count,
        )
        self.repository.insert_task_event(
            task_id,
            "warning",
            "任务已结束，但没有新线索入库；可能全部被地域过滤、页面未解析到有效企业，或已作为重复线索合并。",
        )

    def stop_active_task(self) -> Dict:
        stopped_count = 0
        if self.is_batch_automation_running():
            self.batch_automation_stop_requested = True
        config = get_config()
        process_id_list = list_browser_profile_process_id(config.alibaba_1688_user_data_dir)
        process_id_list.extend(list_browser_profile_process_id(config.qcc_public_web_user_data_dir))
        process_id_list.extend(list_browser_profile_process_id(config.fengniao_public_web_user_data_dir))
        process_id_list.extend(list_browser_profile_process_id(config.douyin_public_web_user_data_dir))
        enterprise_profile_parent = config.qcc_public_web_user_data_dir.parent
        for profile_dir_name in ("aiqicha", "qixin", "tianyancha"):
            process_id_list.extend(list_browser_profile_process_id(enterprise_profile_parent / profile_dir_name))
        stop_process_id_list(process_id_list)
        active_task_list = [
            task for task in self.repository.list_task()
            if task["status"] in (
                TASK_STATUS_PENDING,
                TASK_STATUS_RUNNING,
                TASK_STATUS_COLLECTING,
                TASK_STATUS_WAITING_MANUAL,
                TASK_STATUS_VERIFYING,
                TASK_STATUS_SCORING,
                TASK_STATUS_SAVING,
            )
        ]
        for task in active_task_list:
            self.repository.update_task_status(
                task["id"],
                TASK_STATUS_FAILED,
                total_count=task["total_count"],
                success_count=task["success_count"],
                failed_count=task["failed_count"],
            )
            self.repository.insert_task_event(
                task["id"],
                "error",
                "任务已手动停止：请确认页面状态后重新采集",
            )
            stopped_count += 1
        return {
            "stopped_count": stopped_count,
            "closed_browser_process_count": len(process_id_list),
        }

    def bind_collector_task_event_callback(self, collector, task_id: str) -> None:
        if not hasattr(collector, "set_task_event_callback"):
            return

        def handle_task_event(event_type: str, level: str, message: str) -> None:
            safe_level = level or "info"
            if event_type == "waiting_manual":
                self.repository.update_task_status(task_id, TASK_STATUS_WAITING_MANUAL)
                self.repository.insert_task_event(task_id, safe_level, message)
                return
            if event_type == "manual_resumed":
                self.repository.update_task_status(task_id, TASK_STATUS_COLLECTING)
                self.repository.insert_task_event(task_id, safe_level, message)
                return
            self.repository.insert_task_event(task_id, safe_level, message)

        collector.set_task_event_callback(handle_task_event)

    def bind_collector_existing_lead_identity(self, collector, source_type: str) -> None:
        if not hasattr(collector, "set_existing_lead_identity_list"):
            return
        identity_list = self.repository.list_lead_identity(source_type)
        collector.set_existing_lead_identity_list(identity_list)

    def get_disqualified_reason(self, collected_lead: CollectedLeadDTO, company_verify: CompanyVerifyDTO) -> str:
        reason = get_disqualified_lead_reason(collected_lead)
        if reason:
            return reason
        verify_text = " ".join(
            [
                company_verify.company_name,
                company_verify.company_status,
                company_verify.business_scope,
                company_verify.registered_address,
                company_verify.risk_tag,
                company_verify.failure_reason,
            ]
        )
        return get_disqualified_text_reason(verify_text)

    def save_collected_lead_list(self, task_id: str, task, collected_lead_list) -> tuple:
        success_count = 0
        failed_count = 0
        qcc_used_count = 0
        is_quota_warning_emitted = False
        is_scoring_event_emitted = False
        is_saving_event_emitted = False
        for collected_lead in collected_lead_list:
            try:
                if task["is_qcc_enabled"] == 1:
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_VERIFYING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                company_verify = self.verify_company_if_needed(task, collected_lead, qcc_used_count)
                if company_verify.verification_status == VERIFY_STATUS_QUOTA_LIMITED and not is_quota_warning_emitted:
                    self.repository.insert_task_event(task_id, "warning", "企查查本地额度不足，后续线索将跳过核验")
                    is_quota_warning_emitted = True
                if company_verify.consume_count > 0:
                    qcc_used_count += company_verify.consume_count
                disqualified_reason = self.get_disqualified_reason(collected_lead, company_verify)
                if disqualified_reason:
                    failed_count += 1
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        f"已跳过非正常状态线索：{collected_lead.suspected_company_name}，原因：{disqualified_reason}",
                    )
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_VERIFYING if task["is_qcc_enabled"] == 1 else TASK_STATUS_SCORING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                    continue
                target_region_disqualified_reason = self.get_target_region_disqualified_reason(
                    task,
                    collected_lead,
                    company_verify,
                )
                if target_region_disqualified_reason:
                    failed_count += 1
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        (
                            f"已跳过地区不符线索：{collected_lead.suspected_company_name}，"
                            f"原因：{target_region_disqualified_reason}"
                        ),
                    )
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_VERIFYING if task["is_qcc_enabled"] == 1 else TASK_STATUS_SCORING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                    continue
                if not is_scoring_event_emitted:
                    self.repository.insert_task_event(task_id, "info", "正在进行线索评分与分级")
                    is_scoring_event_emitted = True
                self.repository.update_task_status(
                    task_id,
                    TASK_STATUS_SCORING,
                    total_count=len(collected_lead_list),
                    success_count=success_count,
                    failed_count=failed_count,
                )
                score_result = self.scoring_service.calculate_score(collected_lead, company_verify)
                if not is_saving_event_emitted:
                    self.repository.insert_task_event(task_id, "info", "正在写入线索库并更新任务进度")
                    is_saving_event_emitted = True
                self.repository.update_task_status(
                    task_id,
                    TASK_STATUS_SAVING,
                    total_count=len(collected_lead_list),
                    success_count=success_count,
                    failed_count=failed_count,
                )
                is_inserted = self.save_lead_once(task_id, collected_lead, company_verify, score_result)
                if company_verify.consume_count > 0:
                    self.insert_usage_log(task_id, company_verify)
                if not is_inserted:
                    self.repository.insert_task_event(
                        task_id,
                        "info",
                        f"已合并重复线索：{collected_lead.suspected_company_name}",
                    )
                    self.repository.update_task_status(
                        task_id,
                        TASK_STATUS_SAVING,
                        total_count=len(collected_lead_list),
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                    continue
                success_count += 1
                self.repository.update_task_status(
                    task_id,
                    TASK_STATUS_SAVING,
                    total_count=len(collected_lead_list),
                    success_count=success_count,
                    failed_count=failed_count,
                )
            except Exception as ex:
                failed_count += 1
                self.repository.update_task_status(
                    task_id,
                    TASK_STATUS_SAVING,
                    total_count=len(collected_lead_list),
                    success_count=success_count,
                    failed_count=failed_count,
                )
                logger.exception("Lead processing failed, task_id=%s, error=%s", task_id, ex)
        return success_count, failed_count

    def insert_after_collect_event(self, task_id: str, task, collected_count: int, collector=None) -> None:
        event_message = f"已采集 {collected_count} 条公开线索，开始广东省过滤与评分"
        if task["is_qcc_enabled"] == 1:
            event_message = f"已采集 {collected_count} 条公开线索，开始企查查核验"
        elif task["source_type"] == SOURCE_TYPE_FENGNIAO_PUBLIC_WEB:
            event_message = f"已采集 {collected_count} 条美亚风鸟线索，开始广东省过滤与评分"
        elif task["source_type"] == SOURCE_TYPE_DOUYIN_QCC:
            event_message = f"已采集 {collected_count} 条抖音公开线索，并完成企查查公开页补充核验，开始广东省过滤与评分"
        elif task["source_type"] == SOURCE_TYPE_QCC_PUBLIC_WEB:
            event_message = f"已采集 {collected_count} 条企查查公开线索，开始广东省过滤与评分"
        elif task["source_type"] == SOURCE_TYPE_AI_WEB_SEARCH:
            event_message = f"已采集 {collected_count} 条AI 1688索引线索，开始广东省过滤与评分"
        elif task["source_type"] == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            event_message = (
                f"已采集 {collected_count} 条阿里国际站供应商列表公开线索；"
                "不会自动调用启信宝/企查查，开始广东省过滤与评分"
            )
        elif task["source_type"] in PUBLIC_ENTERPRISE_SOURCE_NAME_MAP:
            source_name = PUBLIC_ENTERPRISE_SOURCE_NAME_MAP[task["source_type"]]
            event_message = f"已采集 {collected_count} 条{source_name}公开线索，开始广东省过滤与评分"
        self.repository.insert_task_event(task_id, "info", event_message)
        if collected_count == 0:
            self.insert_empty_collect_diagnosis_event(task_id, task, collector)
            return
        if task["source_type"] in (
            SOURCE_TYPE_ALIBABA_1688,
            SOURCE_TYPE_ALIBABA_INTERNATIONAL,
        ) and collected_count < int(task.get("collect_limit") or 0):
            diagnostic_message = getattr(collector, "last_collect_diagnostic", "")
            if diagnostic_message:
                self.repository.insert_task_event(task_id, "warning", diagnostic_message)

    def insert_empty_collect_diagnosis_event(self, task_id: str, task, collector=None) -> None:
        keyword_text = task.get("keyword_text", "")
        if task["source_type"] == SOURCE_TYPE_ALIBABA_1688:
            diagnostic_message = getattr(collector, "last_collect_diagnostic", "")
            self.repository.insert_task_event(
                task_id,
                "warning",
                diagnostic_message
                or f"1688本次未采集到公开线索；当前关键词：{keyword_text}。请确认页面正常加载、关键词与行业匹配，且没有登录或验证遮挡。",
            )
            return
        if task["source_type"] == SOURCE_TYPE_AI_WEB_SEARCH:
            diagnostic_message = getattr(collector, "last_collect_diagnostic", "")
            self.repository.insert_task_event(
                task_id,
                "warning",
                diagnostic_message
                or f"AI 1688索引本次未采集到可入库企业；当前关键词：{keyword_text}。请换更具体的产品词，或配置稳定搜索API提高1688索引命中率。",
            )
            return
        if task["source_type"] == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            diagnostic_message = getattr(collector, "last_collect_diagnostic", "")
            self.repository.insert_task_event(
                task_id,
                "warning",
                diagnostic_message
                or f"中国制造网本次未采集到公司信息；当前关键词：{keyword_text}。请换更具体的产品词，例如手机壳工厂、数据线厂家，并确认页面没有访问限制。",
            )
            return
        if task["source_type"] == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            diagnostic_message = getattr(collector, "last_collect_diagnostic", "")
            self.repository.insert_task_event(
                task_id,
                "warning",
                diagnostic_message
                or f"阿里国际站本次未从搜索结果页解析到可入库企业；系统会先尝试原始英文关键词，再补充广东/城市关键词。当前关键词：{keyword_text}。",
            )
            return
        if task["source_type"] == SOURCE_TYPE_FENGNIAO_PUBLIC_WEB:
            self.repository.insert_task_event(
                task_id,
                "warning",
                f"美亚风鸟本次未返回企业。系统已优先尝试广东城市 + 品类长尾词，当前原始关键词：{keyword_text}；该站公开页对泛词命中不稳定，建议补充更具体的企业名或产品词。",
            )
            return
        if task["source_type"] == SOURCE_TYPE_QCC_PUBLIC_WEB:
            self.repository.insert_task_event(
                task_id,
                "warning",
                f"企查查公开页本次未返回企业。系统已优先尝试广东城市 + 品类长尾词；命中仍会受登录状态、验证、关键词和页面结构影响，当前原始关键词：{keyword_text}。",
            )
            return
        if task["source_type"] in PUBLIC_ENTERPRISE_SOURCE_NAME_MAP:
            source_name = PUBLIC_ENTERPRISE_SOURCE_NAME_MAP[task["source_type"]]
            self.repository.insert_task_event(
                task_id,
                "warning",
                f"{source_name}公开页本次未返回可入库企业。系统已优先尝试广东城市 + 品类长尾词；若页面有登录/验证或号码未公开，会跳过当前结果，当前原始关键词：{keyword_text}。",
            )
            return
        if task["source_type"] == SOURCE_TYPE_DOUYIN_QCC:
            self.repository.insert_task_event(
                task_id,
                "warning",
                f"抖音公开链路本次未采集到企业线索。可能是关键词过窄、页面需要登录/验证，或公开结果中没有蓝V/企业主体；当前关键词：{keyword_text}。",
            )
            return
        self.repository.insert_task_event(
            task_id,
            "warning",
            f"本次未采集到公开线索；当前关键词：{keyword_text}，请检查页面是否正常加载或换更精确关键词。",
        )

    def verify_company_if_needed(self, task, collected_lead, qcc_used_count: int) -> CompanyVerifyDTO:
        if task["source_type"] in PUBLIC_WEB_ONLY_SOURCE_TYPE_SET:
            return self.build_public_web_verify(collected_lead)
        if task["is_qcc_enabled"] != 1:
            return self.build_skipped_verify(collected_lead.suspected_company_name, VERIFY_STATUS_SKIPPED)
        if qcc_used_count >= task["qcc_limit"]:
            return self.build_skipped_verify(collected_lead.suspected_company_name, VERIFY_STATUS_QUOTA_LIMITED)
        if not self.has_qcc_quota_remaining():
            return self.build_skipped_verify(collected_lead.suspected_company_name, VERIFY_STATUS_QUOTA_LIMITED)
        return self.qichacha_service.verify_company(
            collected_lead.suspected_company_name,
            collected_lead.industry,
        )

    def has_qcc_quota_remaining(self) -> bool:
        usage_summary = self.repository.get_usage_summary()
        return usage_summary["daily_remaining"] > 0 and usage_summary["monthly_remaining"] > 0

    def build_skipped_verify(self, company_name: str, status: str) -> CompanyVerifyDTO:
        return CompanyVerifyDTO(
            company_name=company_name,
            company_status="待核验",
            business_scope="",
            verification_status=status,
            confidence="low",
            is_success=False,
            consume_count=0,
        )

    def build_public_web_verify(self, collected_lead: CollectedLeadDTO) -> CompanyVerifyDTO:
        return CompanyVerifyDTO(
            company_name=collected_lead.suspected_company_name,
            legal_person=collected_lead.legal_person,
            company_status=collected_lead.company_status or "公开页可见",
            unified_social_credit_code=collected_lead.unified_social_credit_code,
            business_scope=collected_lead.business_scope,
            registered_address=collected_lead.registered_address,
            phone=collected_lead.phone,
            risk_tag=collected_lead.risk_tag,
            verification_status=VERIFY_STATUS_PUBLIC_WEB,
            confidence="medium" if collected_lead.registered_address or collected_lead.company_status else "low",
            is_success=True,
            consume_count=0,
        )

    def insert_usage_log(self, task_id: str, company_verify: CompanyVerifyDTO) -> None:
        current_time = get_current_time_text()
        self.repository.insert_qcc_usage(
            {
                "id": uuid.uuid4().hex,
                "task_id": task_id,
                "company_name": company_verify.company_name,
                "interface_name": DEFAULT_QCC_INTERFACE_NAME,
                "consume_count": company_verify.consume_count,
                "is_success": 1 if company_verify.is_success else 0,
                "failure_reason": company_verify.failure_reason,
                "gmt_create": current_time,
                "gmt_modified": current_time,
            }
        )

    def save_lead_once(self, task_id: str, collected_lead, company_verify, score_result) -> bool:
        lead_data = self.build_lead_data(task_id, collected_lead, company_verify, score_result)
        duplicate_lead_id = self.repository.find_duplicate_lead_id(lead_data)
        if duplicate_lead_id:
            self.repository.update_lead_public_fields(duplicate_lead_id, lead_data)
            return False
        self.repository.insert_lead(lead_data)
        return True

    def build_lead_data(self, task_id, collected_lead, company_verify, score_result):
        current_time = get_current_time_text()
        collected_phone = clean_public_phone_text(collected_lead.phone, include_service=True)
        verified_phone = clean_public_phone_text(company_verify.phone, include_service=True)
        final_phone = collected_phone or verified_phone
        phone_source = collected_lead.phone_source if collected_phone else ("企查查企业电话" if verified_phone else "")
        company_name = company_verify.company_name or collected_lead.suspected_company_name
        company_status = company_verify.company_status
        if company_status in ("待核验", "未核验", "公开页可见", "") and collected_lead.company_status:
            company_status = collected_lead.company_status
        legal_person = company_verify.legal_person or collected_lead.legal_person
        unified_social_credit_code = (
            company_verify.unified_social_credit_code or collected_lead.unified_social_credit_code
        )
        business_scope = company_verify.business_scope or collected_lead.business_scope
        registered_address = company_verify.registered_address or collected_lead.registered_address
        risk_tag = company_verify.risk_tag or collected_lead.risk_tag
        region_info = extract_region_info(
            registered_address=registered_address,
            region_text=collected_lead.region_text,
            company_name=company_name,
            suspected_company_name=collected_lead.suspected_company_name,
            source_keyword=collected_lead.source_keyword,
        )
        return {
            "id": uuid.uuid4().hex,
            "task_id": task_id,
            "source_type": collected_lead.source_type,
            "source_keyword": collected_lead.source_keyword,
            "industry": collected_lead.industry,
            "suspected_company_name": collected_lead.suspected_company_name,
            "company_name": company_name,
            "douyin_nickname": collected_lead.douyin_nickname,
            "product_name": repair_product_name_for_source(
                collected_lead.product_name,
                collected_lead.industry,
                collected_lead.source_keyword,
                business_scope,
                registered_address,
                collected_lead.source_type,
            ),
            "contact_name": collected_lead.contact_name,
            "phone": final_phone,
            "phone_source": phone_source if final_phone else "",
            "website_url": collected_lead.website_url,
            "shop_url": collected_lead.shop_url,
            "profile_url": collected_lead.profile_url,
            "sample_video_url": collected_lead.sample_video_url,
            "is_blue_v": 1 if collected_lead.is_blue_v else 0,
            "is_enterprise_verified": 1 if collected_lead.is_enterprise_verified else 0,
            "company_status": company_status,
            "unified_social_credit_code": unified_social_credit_code,
            "legal_person": legal_person,
            "business_scope": business_scope,
            "registered_address": registered_address,
            "province": region_info["province"],
            "city": region_info["city"],
            "district": region_info["district"],
            "city_source": region_info["city_source"],
            "city_confidence": region_info["city_confidence"],
            "risk_tag": risk_tag,
            "verification_status": company_verify.verification_status,
            "confidence": company_verify.confidence,
            "score": score_result.score,
            "level": score_result.level,
            "assignment_status": ASSIGNMENT_STATUS_UNASSIGNED,
            "gmt_create": current_time,
            "gmt_modified": current_time,
        }

    def build_task_name(self, source_type: str, industry: str) -> str:
        if source_type == SOURCE_TYPE_DOUYIN_QCC:
            source_name = "抖音+企查查"
        elif source_type == SOURCE_TYPE_QCC_PUBLIC_WEB:
            source_name = "企查查"
        elif source_type == SOURCE_TYPE_FENGNIAO_PUBLIC_WEB:
            source_name = "美亚风鸟"
        elif source_type == SOURCE_TYPE_AIQICHA_PUBLIC_WEB:
            source_name = "爱企查"
        elif source_type == SOURCE_TYPE_QIXIN_PUBLIC_WEB:
            source_name = "启信宝"
        elif source_type == SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB:
            source_name = "天眼查"
        elif source_type == SOURCE_TYPE_AI_WEB_SEARCH:
            source_name = "AI 1688搜企"
        elif source_type == SOURCE_TYPE_ALIBABA_1688:
            source_name = "1688采集"
        elif source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            source_name = "阿里国际站"
        elif source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
            source_name = "中国制造网+天眼查"
        elif source_type == SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT:
            source_name = "1688页面助手停用"
        elif source_type == SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT:
            source_name = "1688普通页面导入"
        else:
            source_name = "1688公开页面"
        task_suffix = "供应商采集" if source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL else "线索采集"
        return f"{source_name} {industry} {task_suffix}"

    def normalize_industry(self, industry: str) -> str:
        clean_industry = industry.strip()
        clean_industry = INDUSTRY_ALIAS_MAP.get(clean_industry, clean_industry)
        if clean_industry in ALLOWED_INDUSTRY_SET:
            return clean_industry
        return "服装"

    def normalize_target_city(self, source_type: str, target_city: str) -> str:
        if source_type not in TARGET_CITY_SOURCE_TYPE_SET:
            return ""
        clean_target_city_text = str(target_city or "").strip()
        if clean_target_city_text in ("", "广东", "广东省"):
            return "广东省"
        normalized_city_list = []
        for raw_city in re.split(r"[,，、;/\n\r]+", clean_target_city_text):
            clean_city = str(raw_city or "").strip()
            if clean_city in ("", "广东", "广东省"):
                continue
            city_name = normalize_city_name(clean_city)
            normalized_target_city = f"{city_name}市" if city_name else ""
            if normalized_target_city in GUANGDONG_TARGET_CITY_SET and normalized_target_city not in normalized_city_list:
                normalized_city_list.append(normalized_target_city)
        if normalized_city_list:
            return ",".join(normalized_city_list)
        return "广东省"

    def normalize_target_city_name_list(self, source_type: str, target_city: str) -> List[str]:
        normalized_target_city = self.normalize_target_city(source_type, target_city)
        if not normalized_target_city:
            return []
        if normalized_target_city == "广东省":
            return ["广东省"]
        city_name_list: List[str] = []
        for raw_city in re.split(r"[,，、;/\n\r]+", normalized_target_city):
            city_name = normalize_city_name(raw_city)
            if city_name and f"{city_name}市" in GUANGDONG_TARGET_CITY_SET and city_name not in city_name_list:
                city_name_list.append(city_name)
        return city_name_list or ["广东省"]

    def format_target_city_name_list(self, city_name_list: List[str]) -> str:
        if city_name_list == ["广东省"]:
            return "广东省"
        return "、".join(f"{city_name}市" for city_name in city_name_list)

    def get_lead_reliable_region_info(
        self,
        collected_lead: CollectedLeadDTO,
        company_verify: CompanyVerifyDTO,
    ) -> Dict[str, str]:
        company_name = company_verify.company_name or collected_lead.suspected_company_name
        registered_address = company_verify.registered_address or collected_lead.registered_address
        return extract_region_info(
            registered_address=registered_address,
            region_text=collected_lead.region_text,
            company_name=company_name,
            suspected_company_name=collected_lead.suspected_company_name,
            source_keyword="",
        )

    def get_target_region_disqualified_reason(
        self,
        task,
        collected_lead: CollectedLeadDTO,
        company_verify: CompanyVerifyDTO,
    ) -> str:
        if task.get("source_type", "") == SOURCE_TYPE_ALIBABA_1688:
            return ""
        target_city_name_list = self.normalize_target_city_name_list(
            task.get("source_type", ""),
            task.get("target_city", ""),
        )
        if not target_city_name_list:
            return "" if self.is_guangdong_lead(collected_lead, company_verify) else "非广东省或无法确认广东省"
        if target_city_name_list == ["广东省"]:
            return "" if self.is_guangdong_lead(collected_lead, company_verify) else "非广东省或无法确认广东省"

        target_city_label = self.format_target_city_name_list(target_city_name_list)
        if collected_lead.source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            region_evidence = " ".join([collected_lead.region_text, collected_lead.registered_address])
            if self.is_alibaba_international_target_city_region_text(region_evidence, target_city_name_list):
                return ""
            if self.is_alibaba_international_guangdong_region_text(region_evidence):
                return f"不属于所选城市（{target_city_label}）"
            return f"无法确认属于所选城市（{target_city_label}）"

        region_info = self.get_lead_reliable_region_info(collected_lead, company_verify)
        parsed_city = region_info.get("city", "")
        if parsed_city and parsed_city in target_city_name_list:
            return ""
        if parsed_city:
            return f"不属于所选城市（{target_city_label}），解析城市：{parsed_city}市"
        return f"无法确认属于所选城市（{target_city_label}）"

    def normalize_keyword(self, keywords: List[str], industry: str, source_type: str) -> List[str]:
        clean_keyword_list = []
        for raw_keyword in keywords:
            for keyword in re.split(r"[,，、;/\n\r]+", raw_keyword or ""):
                clean_keyword = keyword.strip()
                if not clean_keyword or self.is_mojibake_keyword(clean_keyword):
                    continue
                clean_keyword_list.append(clean_keyword)
        if clean_keyword_list:
            return clean_keyword_list
        if industry == INDUSTRY_OTHER:
            raise ValueError("其他类目必须填写产品关键词，例如“手持蒸汽熨烫机”或“游戏手柄”。")
        if source_type == SOURCE_TYPE_ALIBABA_1688:
            raise ValueError("1688采集必须填写产品关键词，系统不会自动生成默认关键词。")
        if industry == "3C数码":
            return ["3C批发", "手机壳工厂", "跨境3C"]
        if industry == INDUSTRY_BEAUTY_CARE:
            return ["化妆品工厂", "护肤品OEM", "美妆供应链"]
        return ["服装工厂", "女装批发", "服装OEM"]

    def is_browser_closed_error(self, ex: Exception) -> bool:
        message = str(ex)
        closed_token_list = [
            "Target page, context or browser has been closed",
            "Browser has been closed",
            "Browser closed",
            "Target closed",
        ]
        return any(token in message for token in closed_token_list)

    def split_keyword_text(self, keyword_text: str) -> List[str]:
        return [
            keyword.strip()
            for keyword in re.split(r"[,，、;/\n\r]+", keyword_text or "")
            if keyword.strip()
        ]

    def is_mojibake_keyword(self, keyword: str) -> bool:
        mojibake_token_list = (
            "�",
            "ï¿½",
            "锟",
            "斤拷",
            "茂驴陆",
            "閿",
            "閲",
            "楠",
            "鐢",
            "鑱",
            "绾",
            "鍏",
            "涓",
            "宸",
            "囚",
            "ョ",
            "链将囚",
            "ョ配",
            "宸。",
            "宸ャ",
            "将囚",
        )
        if any(token in keyword for token in mojibake_token_list):
            return True
        question_mark_count = keyword.count("?")
        if question_mark_count == 0:
            return False
        return question_mark_count >= max(len(keyword) // 2, 1)

    def is_guangdong_lead(self, collected_lead: CollectedLeadDTO, company_verify: CompanyVerifyDTO) -> bool:
        if collected_lead.source_type == SOURCE_TYPE_ALIBABA_INTERNATIONAL:
            region_evidence = " ".join(
                [
                    collected_lead.region_text,
                    collected_lead.registered_address,
                ]
            )
            return self.is_alibaba_international_guangdong_region_text(region_evidence)
        if collected_lead.source_type in (
            SOURCE_TYPE_QCC_PUBLIC_WEB,
            SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,
            SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
            SOURCE_TYPE_QIXIN_PUBLIC_WEB,
            SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
        ):
            return (
                is_guangdong_text(collected_lead.suspected_company_name)
                or is_guangdong_text(company_verify.company_name)
                or is_reliable_guangdong_address(collected_lead.registered_address)
                or is_reliable_guangdong_address(company_verify.registered_address)
            )
        region_text = " ".join(
            [
                collected_lead.suspected_company_name,
                collected_lead.region_text,
                collected_lead.registered_address,
                collected_lead.profile_url,
                company_verify.company_name,
                company_verify.registered_address,
                company_verify.business_scope,
            ]
        )
        return is_guangdong_text(region_text)

    def is_alibaba_international_guangdong_region_text(self, text: str) -> bool:
        clean_text = str(text or "")
        if is_guangdong_text(clean_text):
            return True
        clean_text = clean_text.lower()
        return any(
            re.search(rf"\b{re.escape(token)}\b", clean_text)
            for token in ALIBABA_INTERNATIONAL_GUANGDONG_REGION_TOKEN_LIST
        )

    def is_alibaba_international_target_city_region_text(self, text: str, target_city_name_list: List[str]) -> bool:
        clean_text = str(text or "").lower()
        if not clean_text:
            return False
        for city_name in target_city_name_list:
            city_token = ALIBABA_INTERNATIONAL_CITY_TOKEN_MAP.get(city_name)
            if city_token and re.search(rf"\b{re.escape(city_token)}\b", clean_text):
                return True
            if city_name in text or f"{city_name}市" in text:
                return True
        return False
