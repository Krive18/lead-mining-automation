import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from app.service.qixin_api_service import QixinApiError, QixinApiService
from app.service.tianyancha_verification_service import (
    TIANYANCHA_JOB_STATUS_COMPLETED,
    TIANYANCHA_JOB_STATUS_FAILED,
    TIANYANCHA_JOB_STATUS_RUNNING,
    TIANYANCHA_JOB_STATUS_STOPPED,
    TIANYANCHA_STATUS_MATCHED,
    TIANYANCHA_STATUS_NOT_FOUND,
    TianyanchaVerificationJob,
    TianyanchaVerificationService,
)


QIXIN_RESULT_HEADER_LIST = [
    "启信宝反证状态",
    "启信宝匹配企业",
    "法定代表人",
    "联系人/最大股东",
    "联系电话",
    "电话来源",
    "企业状态",
    "统一社会信用代码",
    "企业地址",
    "经营范围",
    "风险标签",
    "启信宝详情页",
    "启信宝检索词",
    "启信宝反证备注",
    "启信宝反证时间",
]


class QixinVerificationService(TianyanchaVerificationService):
    def __init__(
        self,
        qixin_api_service: Optional[QixinApiService] = None,
        config=None,
        sleep_func: Callable[[float], None] = time.sleep,
    ):
        super().__init__(config=config, sleep_func=sleep_func)
        self.qixin_api_service = qixin_api_service or QixinApiService(config=self.config)

    def create_verification_job(
        self,
        excel_base64: str,
        file_name: str,
        company_name_column_index: int = 0,
        request_interval_seconds: float = 0.8,
    ) -> Dict:
        self.qixin_api_service.assert_configured()
        clean_interval = max(0.0, min(float(request_interval_seconds or 0.0), 60.0))
        snapshot = super().create_verification_job(
            excel_base64=excel_base64,
            file_name=file_name,
            company_name_column_index=company_name_column_index,
            batch_size=1,
            jitter_min_seconds=clean_interval,
            jitter_max_seconds=clean_interval,
            batch_cooldown_seconds=0,
        )
        with self.job_lock:
            job = self.get_verification_job(snapshot["job_id"])
            job.current_message = "等待启信宝API反证"
            if job.event_list:
                job.event_list[0]["message"] = f"启信宝反证任务已创建：{len(job.company_row_list)} 家企业"
            return self.build_job_snapshot(job)

    def run_verification_job(self, job_id: str) -> None:
        with self.job_lock:
            job = self.get_verification_job(job_id)
            if job.stop_requested:
                job.current_message = "正在安全停止，并保存已完成结果"
            else:
                job.status = TIANYANCHA_JOB_STATUS_RUNNING
                job.current_message = "正在启动启信宝API反证"
            job.error_message = ""
        try:
            if self.is_stop_requested(job):
                self.finish_stopped_job(job)
                return
            if not job.company_row_list:
                self.finish_job(job)
                return
            total_count = len(job.company_row_list)
            for row_offset, company_row in enumerate(job.company_row_list):
                if self.is_stop_requested(job):
                    self.finish_stopped_job(job)
                    return
                if row_offset > 0 and not self.wait_before_request(job):
                    self.finish_stopped_job(job)
                    return
                company_name = company_row.get("company_name", "")
                with self.job_lock:
                    job.status = TIANYANCHA_JOB_STATUS_RUNNING
                    job.current_row_index = company_row.get("row_index", row_offset + 2)
                    job.current_company_name = company_name
                    job.current_search_keyword = company_name
                    job.current_batch_index = row_offset + 1
                    job.current_message = f"正在查询 {row_offset + 1}/{total_count}：{company_name}"
                self.append_job_event(job, "info", f"启信宝查询 {row_offset + 1}/{total_count}：{company_name}")
                try:
                    api_result = self.qixin_api_service.query_company(company_name, "")
                    verification_result = self.build_result_from_lead(company_name, api_result.lead)
                    endpoint_summary = "，".join(
                        f"{name}:{'成功' if status.get('success') else status.get('message') or '未完成'}"
                        for name, status in api_result.endpoint_status.items()
                    )
                    self.append_job_event(job, "info", f"启信宝匹配成功：{company_name}；{endpoint_summary}")
                except QixinApiError as ex:
                    verification_result = self.build_qixin_error_result(company_name, ex)
                    self.append_job_event(job, "warning", f"启信宝查询未完成：{company_name}；{ex}")
                    with self.job_lock:
                        job.result_list.append(verification_result)
                    if ex.is_authorization_denied():
                        self.append_remaining_unconfirmed(job, row_offset + 1, str(ex))
                        break
                    continue
                with self.job_lock:
                    job.result_list.append(verification_result)
            self.finish_job(job)
        except Exception as ex:
            with self.job_lock:
                job.status = TIANYANCHA_JOB_STATUS_FAILED
                job.error_message = str(ex)[:300]
                job.current_message = "启信宝反证失败"
            self.append_job_event(job, "error", f"启信宝反证失败：{ex}")

    def wait_before_request(self, job: TianyanchaVerificationJob) -> bool:
        wait_seconds = max(0.0, float(job.jitter_min_seconds or 0.0))
        if wait_seconds <= 0:
            return not self.is_stop_requested(job)
        with self.job_lock:
            job.current_message = f"API请求间隔，等待 {wait_seconds:g} 秒"
        if self.sleep_func is time.sleep:
            job.stop_event.wait(wait_seconds)
        else:
            self.sleep_func(wait_seconds)
        return not self.is_stop_requested(job)

    def append_remaining_unconfirmed(self, job: TianyanchaVerificationJob, start_index: int, reason: str) -> None:
        remaining_row_list = job.company_row_list[start_index:]
        with self.job_lock:
            for company_row in remaining_row_list:
                job.result_list.append(
                    self.build_unconfirmed_result(
                        company_row.get("company_name", ""),
                        f"启信宝授权不可用，未继续调用：{reason}",
                    )
                )
            job.error_message = reason[:300]
        self.append_job_event(job, "warning", f"启信宝授权不可用，已停止后续 {len(remaining_row_list)} 次API请求")

    def build_qixin_error_result(self, company_name: str, error: QixinApiError):
        error_message = str(error)
        if error.status == "201" or any(
            token in error_message for token in ("未找到", "无结果", "无数据", "未返回企业数据")
        ):
            result = self.build_unconfirmed_result(company_name, error_message)
            result.status = TIANYANCHA_STATUS_NOT_FOUND
            return result
        return self.build_unconfirmed_result(company_name, error_message)

    def build_result_from_lead(self, company_name, lead):
        result = super().build_result_from_lead(company_name, lead)
        if result.status == TIANYANCHA_STATUS_MATCHED:
            result.remark = "启信宝API精准匹配成功"
        return result

    def finish_job(self, job: TianyanchaVerificationJob) -> None:
        if self.is_stop_requested(job):
            self.finish_stopped_job(job)
            return
        summary = self.write_result_exports(job.header_list, job.company_row_list, job.result_list, job.file_name)
        with self.job_lock:
            job.status = TIANYANCHA_JOB_STATUS_COMPLETED
            job.current_row_index = 0
            job.current_company_name = ""
            job.current_search_keyword = ""
            job.current_message = "启信宝反证完成"
            job.file_path = summary.get("file_path", "")
            job.file_name_export = summary.get("file_name", "")
            job.download_url = summary.get("download_url", "")
        self.append_job_event(job, "info", "启信宝反证完成，已生成结果表")

    def finish_stopped_job(self, job: TianyanchaVerificationJob) -> None:
        processed_count = len(job.result_list)
        summary = self.write_result_exports(
            job.header_list,
            job.company_row_list[:processed_count],
            job.result_list,
            job.file_name,
        )
        with self.job_lock:
            job.status = TIANYANCHA_JOB_STATUS_STOPPED
            job.current_row_index = 0
            job.current_company_name = ""
            job.current_search_keyword = ""
            job.current_message = f"已安全停止，已保存 {processed_count} 条结果"
            job.file_path = summary.get("file_path", "")
            job.file_name_export = summary.get("file_name", "")
            job.download_url = summary.get("download_url", "")
        self.append_job_event(job, "info", f"启信宝反证已停止，已生成 {processed_count} 条部分结果")

    def write_result_sheet(self, sheet, header_list, row_result_pair_list) -> None:
        sheet.append(list(header_list) + QIXIN_RESULT_HEADER_LIST)
        for company_row, result in row_result_pair_list:
            sheet.append(
                list(company_row.get("row_values", []))
                + [
                    result.status,
                    result.matched_company_name,
                    result.legal_person,
                    result.contact_name,
                    result.phone,
                    result.phone_source,
                    result.company_status,
                    result.unified_social_credit_code,
                    result.registered_address,
                    result.business_scope,
                    result.risk_tag,
                    result.profile_url,
                    result.search_keyword,
                    result.remark,
                    result.verified_at,
                ]
            )

    def build_export_file_path(self, file_name: str) -> Path:
        export_dir = Path(self.config.export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(file_name).stem or "qixin_verification"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return export_dir / f"{stem}_qixin_verification_{timestamp}.xlsx"
