import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from conf.logging_conf import app_logger
from conf.settings import settings
from crud import create_task_record, update_task_record_status
from schemas.search_schema import CandidateResultItem, SearchRequest, StructuredResultItem
from schemas.task_schema import TaskItem, TaskStatus
from utils.excel_service import export_results_to_excel
from utils.retriever import build_rebuild_prompt_input
from utils.search_client import search_web
from utils.structured_result_builder import build_structured_results
from utils.task_service_helpers import (
    build_candidates,
    build_fallback_structured_items,
    build_result_payload,
    build_task_item,
    clean_text,
    select_top_k_results,
)
from datetime import datetime, timezone
from schemas.task_runtime_schema import StageTimestampPatch


def build_stage_update(stage: str) -> StageTimestampPatch:
    now = datetime.now(timezone.utc)
    mapping = {
        "search": StageTimestampPatch(search_finished_at=now),
        "llm": StageTimestampPatch(llm_finished_at=now),
        "export": StageTimestampPatch(export_finished_at=now),
    }
    return mapping.get(stage, StageTimestampPatch())


logger = app_logger.bind(module="task_service")

FIXED_TOP_K = 5
PREVIEW_ITEM_LIMIT = 3
REBUILD_SUMMARY_CHAR_LIMIT = 120


def build_task_id() -> str:
    """生成用于任务查询和日志追踪的短 task_id。"""
    return uuid.uuid4().hex[:8]


async def extract_structured_results(
    *,
    task_id: str,
    query: str,
    top_results: list[CandidateResultItem],
    rebuilt_prompt_input_text: str,
    max_results: int,
) -> list[StructuredResultItem]:
    """执行结构化抽取并在失败时回退到候选结果。"""
    if not top_results:
        logger.info("task={} stage=structured_results skipped=no_top_candidates", task_id)
        return []

    task = build_structured_results(
        query=query,
        rebuilt_prompt_input_text=rebuilt_prompt_input_text,
        max_output_items=max_results,
    )
    
    timeout_seconds = settings.structured_stage_timeout_seconds
    if timeout_seconds > 0:
        task = asyncio.wait_for(task, timeout=timeout_seconds)

    try:
        items = await task
    except Exception as exc:
        logger.warning(
            "task={} stage=structured_results_fallback reason={}", task_id, exc
        )
        return build_fallback_structured_items(
            query=query,
            top_results=top_results,
            max_results=max_results,
        )

    if items:
        return items

    logger.warning(
        "task={} stage=structured_results_fallback reason=empty_structured_results",
        task_id,
    )
    return build_fallback_structured_items(
        query=query,
        top_results=top_results,
        max_results=max_results,
    )


async def create_pending_task(request: SearchRequest, db: AsyncSession) -> TaskItem:
    """创建 created 任务记录并返回对外任务对象。"""
    task_id = build_task_id()
    query = clean_text(request.query)
    await create_task_record(
        db,
        {
            "task_id": task_id,
            "query": query,
            "status": TaskStatus.CREATED,
            **build_result_payload([]),
        },
    )
    return build_task_item(
        task_id=task_id,
        query=query,
        status=TaskStatus.CREATED,
        message="任务已创建",
        preview_limit=PREVIEW_ITEM_LIMIT,
    )


async def run_search_task(
    task_id: str,
    request: SearchRequest,
    db: AsyncSession,
) -> TaskItem:
    """编排搜索、结构化、导出和任务状态更新全流程。"""
    query = clean_text(request.query)
    try:
        await update_task_record_status(db, task_id, TaskStatus.RUNNING)
        fetch_limit = max(FIXED_TOP_K, request.max_results, settings.search_result_limit)

        try:
            search_results = await search_web(query, max_results=fetch_limit)
        except Exception as exc:
            logger.warning("task={} stage=results_exhausted reason={}", task_id, exc)
            await update_task_record_status(
                db,
                task_id=task_id,
                status=TaskStatus.FAILED,
                extra_data=build_result_payload([]),
            )
            return build_task_item(
                task_id=task_id,
                query=query,
                status=TaskStatus.FAILED,
                message="联网搜索超时或上游搜索失败，当前未能获取结果",
                preview_limit=PREVIEW_ITEM_LIMIT,
            )

        candidates = build_candidates(
            task_id,
            query,
            select_top_k_results(query, search_results, top_k=FIXED_TOP_K),
            search_provider=settings.search_provider,
        )
        logger.info("task={} stage=results count={}", task_id, len(candidates))

        rebuilt_prompt_input_text = ""
        if candidates:
            rebuilt_prompt_input_text = build_rebuild_prompt_input(
                query,
                candidates,
                max_items=FIXED_TOP_K,
                max_summary_len=REBUILD_SUMMARY_CHAR_LIMIT,
            )
            logger.info(
                "task={} stage=rebuild_prompt chars={}",
                task_id,
                len(rebuilt_prompt_input_text),
            )

        final_items = (
            await extract_structured_results(
                task_id=task_id,
                query=query,
                top_results=candidates,
                rebuilt_prompt_input_text=rebuilt_prompt_input_text,
                max_results=request.max_results,
            )
        )[: request.max_results]
        logger.info(
            "task={} stage=structured_results count={}",
            task_id,
            len(final_items),
        )

        excel_path = export_results_to_excel(final_items) if final_items else None
        logger.info(
            "task={} stage=finalize final_count={} excel={}",
            task_id,
            len(final_items),
            excel_path or "",
        )
        await update_task_record_status(
            db,
            task_id=task_id,
            status=TaskStatus.SUCCESS,
            extra_data=build_result_payload(final_items, excel_path),
        )
        return build_task_item(
            task_id=task_id,
            query=query,
            status=TaskStatus.SUCCESS,
            message="任务执行完成" if final_items else "未找到可用结果",
            result_items=final_items,
            excel_path=excel_path,
            preview_limit=PREVIEW_ITEM_LIMIT,
        )
    except Exception as exc:
        error_message = str(exc)
        logger.exception("task={} stage=failed error={}", task_id, exc)
        try:
            await update_task_record_status(
                db,
                task_id=task_id,
                status=TaskStatus.FAILED,
                extra_data={"error_message": error_message},
            )
        except Exception as status_exc:
            logger.exception(
                "task={} stage=failed_status_update error={}", task_id, status_exc
            )
            raise

        return build_task_item(
            task_id=task_id,
            query=query,
            status=TaskStatus.FAILED,
            message=f"任务失败: {error_message}",
            error=error_message,
            preview_limit=PREVIEW_ITEM_LIMIT,
        )
