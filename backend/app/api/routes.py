from pathlib import Path
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.core.constant import SOURCE_TYPE_ALIBABA_1688, SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT
from app.core.config import get_config
from app.model.schema import (
    Alibaba1688ExistenceColumnPreviewRequestDTO,
    Alibaba1688ExistenceVerificationRequestDTO,
    Alibaba1688SnapshotDTO,
    BatchAutomationCreateDTO,
    ExportCreateDTO,
    QixinVerificationColumnPreviewRequestDTO,
    QixinVerificationRequestDTO,
    QixinEnrichmentCreateDTO,
    TaskCreateDTO,
    TianyanchaEnrichmentCreateDTO,
    TianyanchaVerificationColumnPreviewRequestDTO,
    TianyanchaVerificationRequestDTO,
    UsageSettingDTO,
)
from app.repository.lead_repository import LeadRepository
from app.service.alibaba_1688_existence_service import Alibaba1688ExistenceService
from app.service.export_service import ExportService
from app.service.qixin_verification_service import QixinVerificationService
from app.service.task_service import TaskService
from app.service.tianyancha_verification_service import TianyanchaVerificationService

router = APIRouter(prefix="/api")
repository = LeadRepository()
task_service = TaskService(repository)
export_service = ExportService(repository)
alibaba_1688_existence_service = Alibaba1688ExistenceService()
tianyancha_verification_service = TianyanchaVerificationService()
qixin_verification_service = QixinVerificationService()
BACKEND_DIR = Path(__file__).resolve().parents[2]
NO_STORE_HEADERS = {"Cache-Control": "no-store, max-age=0"}
CREATE_TASK_LOCK = Lock()


@router.get("/health")
def get_health():
    return {"status": "ok"}


@router.get("/dashboard")
def get_dashboard():
    return repository.get_dashboard()


@router.get("/ai/status")
def get_ai_status():
    config = get_config()
    return {
        "provider": "deepseek",
        "enabled": bool(config.ai_page_recognition_enabled and config.deepseek_api_key),
        "api_key_configured": bool(config.deepseek_api_key),
        "model": config.deepseek_model,
        "base_url": config.deepseek_base_url,
        "max_input_chars": config.deepseek_max_input_chars,
    }


@router.get("/qixin/status")
def get_qixin_status():
    return task_service.qixin_api_service.get_connection_status()


@router.get("/tasks")
def list_task():
    return repository.list_task()


@router.post("/tasks")
def create_task(request: TaskCreateDTO, background_tasks: BackgroundTasks):
    with CREATE_TASK_LOCK:
        if task_service.is_batch_automation_running():
            raise HTTPException(status_code=409, detail="自动化批量任务正在运行，请等待完成后再启动新任务。")
        if request.source_type == SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT:
            raise HTTPException(status_code=400, detail="1688页面助手已停用，请使用1688普通页面导入书签或1688自动采集")
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再启动新任务")
        try:
            task_service.assert_task_browser_profile_available(request.source_type)
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        task_id = task_service.create_task(request)
    background_tasks.add_task(task_service.run_task, task_id)
    return {"task_id": task_id}


@router.post("/ai/lead-discovery/tasks")
def create_ai_lead_discovery_task(request: TaskCreateDTO, background_tasks: BackgroundTasks):
    with CREATE_TASK_LOCK:
        if task_service.is_batch_automation_running():
            raise HTTPException(status_code=409, detail="自动化批量任务正在运行，请等待完成后再启动新任务。")
        if request.source_type == SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT:
            raise HTTPException(status_code=400, detail="1688页面助手已停用，请使用1688普通页面导入书签或1688自动采集")
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再启动新任务。")
        try:
            task_service.assert_task_browser_profile_available(request.source_type)
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        task_id = task_service.create_ai_lead_discovery_task(request)
    background_tasks.add_task(task_service.run_task, task_id)
    return {"task_id": task_id}


@router.post("/tasks/batch-automation")
def create_batch_automation(request: BatchAutomationCreateDTO, background_tasks: BackgroundTasks):
    with CREATE_TASK_LOCK:
        if request.source_type == SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT:
            raise HTTPException(status_code=400, detail="1688页面助手已停用，请使用1688自动采集或1688 + 天眼查。")
        if task_service.is_batch_automation_running():
            raise HTTPException(status_code=409, detail="已有自动化批量任务正在运行，请等待完成后再启动新的自动化。")
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再启动自动化。")
        try:
            task_service.assert_task_browser_profile_available(request.source_type)
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        automation_id = ""
        try:
            automation_id = task_service.reserve_batch_automation()
            first_task_id = task_service.create_batch_automation_task(request, automation_id, 1)
        except RuntimeError as ex:
            if automation_id:
                task_service.release_batch_automation()
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        except Exception as ex:
            if automation_id:
                task_service.release_batch_automation()
            raise HTTPException(status_code=400, detail=str(ex)) from ex
    background_tasks.add_task(task_service.run_reserved_batch_automation, automation_id, request, first_task_id)
    return {
        "automation_id": automation_id,
        "first_task_id": first_task_id,
        "batch_count": request.batch_count,
        "batch_collect_limit": request.batch_collect_limit,
        "cooldown_seconds": request.cooldown_seconds,
    }


@router.post("/tasks/stop-active")
def stop_active_task():
    return task_service.stop_active_task()


@router.post("/tasks/tianyancha-enrichment")
def create_tianyancha_enrichment_task(request: TianyanchaEnrichmentCreateDTO, background_tasks: BackgroundTasks):
    with CREATE_TASK_LOCK:
        if task_service.is_batch_automation_running():
            raise HTTPException(status_code=409, detail="自动化批量任务正在运行，请等待完成后再启动天眼查补全。")
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再启动天眼查补全。")
        try:
            task_service.assert_task_browser_profile_available("tianyancha_public_web")
            task_id = task_service.create_tianyancha_enrichment_task(request)
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        except Exception as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
    background_tasks.add_task(
        task_service.run_tianyancha_enrichment_task,
        task_id,
        request.task_id,
        request.pacing_mode,
    )
    return {
        "task_id": task_id,
        "limit": request.limit,
        "source_task_id": request.task_id,
        "pacing_mode": request.pacing_mode,
    }


@router.post("/tasks/qixin-enrichment")
def create_qixin_enrichment_task(request: QixinEnrichmentCreateDTO, background_tasks: BackgroundTasks):
    with CREATE_TASK_LOCK:
        if task_service.is_batch_automation_running():
            raise HTTPException(status_code=409, detail="自动化批量任务正在运行，请等待完成后再启动启信宝补全。")
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再启动启信宝补全。")
        try:
            task_id = task_service.create_qixin_enrichment_task(request)
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        except Exception as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
    background_tasks.add_task(
        task_service.run_qixin_enrichment_task,
        task_id,
        request.task_id,
    )
    return {
        "task_id": task_id,
        "limit": request.limit,
        "source_task_id": request.task_id,
        "pacing_mode": "api",
    }


@router.post("/browser-warmup/tianyancha")
def start_tianyancha_warmup():
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再打开天眼查预热")
    try:
        return task_service.start_tianyancha_warmup()
    except RuntimeError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex


@router.post("/browser-warmup/1688")
def start_alibaba_1688_warmup():
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再打开1688预登录")
    try:
        return task_service.start_alibaba_1688_warmup()
    except RuntimeError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex


@router.post("/browser-warmup/made-in-china")
def start_made_in_china_warmup():
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再打开中国制造网预登录")
    try:
        return task_service.start_made_in_china_warmup()
    except RuntimeError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex


@router.post("/page-snapshots/1688")
def import_1688_page_snapshot(request: Alibaba1688SnapshotDTO):
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再导入当前页面")
    try:
        return task_service.import_1688_snapshot(request)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.get("/page-snapshots/1688/bookmarklet")
def get_1688_bookmarklet_page():
    file_path = BACKEND_DIR / "tools" / "1688_page_import_bookmarklet.html"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="1688 bookmarklet page not found")
    return FileResponse(file_path, media_type="text/html; charset=utf-8", headers=NO_STORE_HEADERS)


@router.get("/page-snapshots/1688/bookmarklet-script")
def get_1688_bookmarklet_script():
    file_path = BACKEND_DIR / "tools" / "1688_page_import_bookmarklet.js"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="1688 bookmarklet script not found")
    return FileResponse(file_path, media_type="application/javascript; charset=utf-8", headers=NO_STORE_HEADERS)


@router.post("/1688-existence-verifications")
def create_1688_existence_verification(
    request: Alibaba1688ExistenceVerificationRequestDTO,
    background_tasks: BackgroundTasks,
):
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再进行1688反证")
    try:
        snapshot = alibaba_1688_existence_service.create_verification_job(
            excel_base64=request.file_content_base64,
            file_name=request.file_name,
            company_name_column_index=request.company_name_column_index,
        )
        background_tasks.add_task(alibaba_1688_existence_service.run_verification_job, snapshot["job_id"])
        return snapshot
    except RuntimeError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.get("/1688-existence-verifications/{job_id}")
def get_1688_existence_verification(job_id: str):
    try:
        return alibaba_1688_existence_service.get_verification_job_snapshot(job_id)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="1688反证任务不存在或已过期") from ex


@router.post("/1688-existence-verifications/columns")
def preview_1688_existence_verification_columns(request: Alibaba1688ExistenceColumnPreviewRequestDTO):
    try:
        return alibaba_1688_existence_service.preview_excel_columns_base64(
            excel_base64=request.file_content_base64,
            file_name=request.file_name,
        )
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.post("/tianyancha-verifications")
def create_tianyancha_verification(
    request: TianyanchaVerificationRequestDTO,
    background_tasks: BackgroundTasks,
):
    with CREATE_TASK_LOCK:
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再进行天眼查反证")
        if tianyancha_verification_service.has_active_job():
            raise HTTPException(status_code=409, detail="已有天眼查反证任务正在运行，请等待完成后再启动新任务")
        try:
            task_service.assert_task_browser_profile_available("tianyancha_public_web")
            snapshot = tianyancha_verification_service.create_verification_job(
                excel_base64=request.file_content_base64,
                file_name=request.file_name,
                company_name_column_index=request.company_name_column_index,
                batch_size=request.batch_size,
                jitter_min_seconds=request.jitter_min_seconds,
                jitter_max_seconds=request.jitter_max_seconds,
                batch_cooldown_seconds=request.batch_cooldown_seconds,
            )
            background_tasks.add_task(tianyancha_verification_service.run_verification_job, snapshot["job_id"])
            return snapshot
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        except Exception as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.get("/tianyancha-verifications/latest")
def get_latest_tianyancha_verification():
    return tianyancha_verification_service.get_latest_verification_job_snapshot()


@router.get("/tianyancha-verifications/history")
def list_tianyancha_verification_history(limit: int = 20):
    return tianyancha_verification_service.list_verification_job_history(limit=limit)


@router.post("/tianyancha-verifications/{job_id}/stop")
def stop_tianyancha_verification(job_id: str):
    try:
        return tianyancha_verification_service.stop_verification_job(job_id)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="天眼查反证任务不存在或已过期") from ex


@router.get("/tianyancha-verifications/{job_id}")
def get_tianyancha_verification(job_id: str):
    try:
        return tianyancha_verification_service.get_verification_job_snapshot(job_id)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="天眼查反证任务不存在或已过期") from ex


@router.post("/tianyancha-verifications/columns")
def preview_tianyancha_verification_columns(request: TianyanchaVerificationColumnPreviewRequestDTO):
    try:
        return tianyancha_verification_service.preview_excel_columns_base64(
            excel_base64=request.file_content_base64,
            file_name=request.file_name,
        )
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.post("/qixin-verifications")
def create_qixin_verification(
    request: QixinVerificationRequestDTO,
    background_tasks: BackgroundTasks,
):
    with CREATE_TASK_LOCK:
        if repository.get_active_task_count() > 0:
            raise HTTPException(status_code=409, detail="已有采集任务正在运行，请等待完成后再进行启信宝反证")
        if qixin_verification_service.has_active_job():
            raise HTTPException(status_code=409, detail="已有启信宝反证任务正在运行，请等待完成后再启动新任务")
        try:
            snapshot = qixin_verification_service.create_verification_job(
                excel_base64=request.file_content_base64,
                file_name=request.file_name,
                company_name_column_index=request.company_name_column_index,
                request_interval_seconds=request.request_interval_seconds,
            )
            background_tasks.add_task(qixin_verification_service.run_verification_job, snapshot["job_id"])
            return snapshot
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        except Exception as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.get("/qixin-verifications/latest")
def get_latest_qixin_verification():
    return qixin_verification_service.get_latest_verification_job_snapshot()


@router.get("/qixin-verifications/history")
def list_qixin_verification_history(limit: int = 20):
    return qixin_verification_service.list_verification_job_history(limit=limit)


@router.post("/qixin-verifications/{job_id}/stop")
def stop_qixin_verification(job_id: str):
    try:
        return qixin_verification_service.stop_verification_job(job_id)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="启信宝反证任务不存在或已过期") from ex


@router.get("/qixin-verifications/{job_id}")
def get_qixin_verification(job_id: str):
    try:
        return qixin_verification_service.get_verification_job_snapshot(job_id)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="启信宝反证任务不存在或已过期") from ex


@router.post("/qixin-verifications/columns")
def preview_qixin_verification_columns(request: QixinVerificationColumnPreviewRequestDTO):
    try:
        return qixin_verification_service.preview_excel_columns_base64(
            excel_base64=request.file_content_base64,
            file_name=request.file_name,
        )
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.get("/leads")
def list_lead(
    level: str = "",
    source_type: str = "",
    source_group: str = "",
    industry: str = "",
    keyword: str = "",
    city: str = "",
    assignment_status: str = "",
    page: int = 1,
    page_size: int = 50,
):
    return repository.list_lead(
        level=level,
        source_type=source_type,
        source_group=source_group,
        industry=industry,
        keyword=keyword,
        city=city,
        assignment_status=assignment_status,
        page=page,
        page_size=page_size,
    )


@router.delete("/leads")
def clear_lead():
    if repository.get_active_task_count() > 0:
        raise HTTPException(status_code=409, detail="任务运行中，暂不能清空线索库")
    deleted_count = repository.clear_lead()
    return {"deleted_count": deleted_count}


@router.get("/usage/summary")
def get_usage_summary():
    return repository.get_usage_summary()


@router.get("/usage/settings")
def get_usage_setting():
    return repository.get_usage_setting()


@router.put("/usage/settings")
def update_usage_setting(request: UsageSettingDTO):
    repository.update_usage_setting(request.daily_quota, request.monthly_quota)
    return repository.get_usage_setting()


@router.get("/logs")
def list_task_event(limit: int = 80):
    return repository.list_task_event(limit=limit)


@router.get("/keywords")
def list_keyword_config():
    return repository.list_keyword_config()


@router.post("/exports")
def create_export(request: ExportCreateDTO):
    result = export_service.create_export(request)
    return result


@router.get("/exports/{file_name}")
def download_export(file_name: str):
    config = get_config()
    if "/" in file_name or "\\" in file_name or Path(file_name).name != file_name:
        raise HTTPException(status_code=400, detail="Invalid export file name")
    export_dir = config.export_dir.resolve()
    file_path = (export_dir / file_name).resolve()
    if file_path.parent != export_dir:
        raise HTTPException(status_code=400, detail="Invalid export file name")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    return FileResponse(
        file_path,
        filename=file_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
