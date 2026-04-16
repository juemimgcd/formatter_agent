import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from agent.runner import run_agent
from conf.logging_conf import app_logger
from crud import (
    create_task_record,
    update_task_record_status,
)
from schemas.registry import resolve_output_schema
from schemas.search_schema import SearchRequest, StructuredResultItem
from schemas.task_schema import TaskItem, TaskStatus
from utils.excel_service import export_results_to_excel
from utils.exceptions import format_exception
from utils.retriever import build_rebuild_prompt_input
from utils.search_client import search_web
from utils.structured_result_builder import build_structured_results
from utils.task_service_helpers import (
    build_candidates,
    build_fallback_structured_items,
    build_result_payload,
    build_task_item,
    clean_text,
    evaluate_result_quality,
    select_top_candidates,
)
from utils.intent_parser import parse_search_intent


logger = app_logger.bind(module="task_service")

PREVIEW_ITEM_LIMIT = 3


def build_task_id() -> str:
    """生成用于任务查询和日志追踪的短 task_id。"""
    # 生成一个便于查询和追踪的短任务编号。
    return uuid.uuid4().hex[:8]


async def create_pending_task(request: SearchRequest, db: AsyncSession) -> TaskItem:
    """创建 created 任务记录并返回对外任务对象。"""
    # 创建初始任务记录并返回前端可直接使用的任务信息。
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
    """执行状态驱动的 Agent Loop，并更新任务状态。"""
    # 任务服务只负责落库和响应适配，决策与动作执行交给 agent runtime。
    query = clean_text(request.query)

    try:
        await update_task_record_status(db, task_id, TaskStatus.RUNNING)
        agent_output = await run_agent(
            query,
            task_id=task_id,
            max_results=request.max_results,
            parse_intent_func=parse_search_intent,
            resolve_schema_func=resolve_output_schema,
            search_func=search_web,
            build_candidates_func=build_candidates,
            select_top_candidates_func=select_top_candidates,
            build_rebuild_prompt_input_func=build_rebuild_prompt_input,
            build_structured_results_func=build_structured_results,
            build_fallback_structured_items_func=build_fallback_structured_items,
            evaluate_result_quality_func=evaluate_result_quality,
            export_results_to_excel_func=export_results_to_excel,
        )
        result = agent_output.result

        if agent_output.stop_reason == "search_failed":
            error_message = result.error or "search failed"
            logger.warning(
                "task={} stage=search_failed reason={} trace={}",
                task_id,
                error_message,
                [trace.model_dump(mode="json") for trace in agent_output.trace],
            )
            await update_task_record_status(
                db,
                task_id=task_id,
                status=TaskStatus.FAILED,
                extra_data=build_result_payload([], error_message=error_message),
            )
            return build_task_item(
                task_id=task_id,
                query=query,
                status=TaskStatus.FAILED,
                message="联网搜索超时或上游搜索失败，当前未能获取结果",
                error=error_message,
                preview_limit=PREVIEW_ITEM_LIMIT,
                warnings=agent_output.warnings,
            )

        final_items = list(result.items)[: request.max_results]
        excel_path = result.excel_path
        used_fallback = result.used_fallback
        result_quality = result.result_quality
        warnings = list(agent_output.warnings)

        logger.info(
            "task={} stage=agent_final stop_reason={} raw_count={} selected_count={} "
            "final_count={} quality={} fallback={} trace={}",
            task_id,
            agent_output.stop_reason,
            result.raw_result_count,
            result.selected_candidate_count,
            len(final_items),
            result_quality,
            used_fallback,
            [trace.model_dump(mode="json") for trace in agent_output.trace],
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
            used_fallback=used_fallback,
            result_quality=result_quality,
            warnings=warnings,
        )
    except Exception as exc:
        error_message = format_exception(exc)
        logger.exception("task={} stage=failed error={}", task_id, error_message)
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
