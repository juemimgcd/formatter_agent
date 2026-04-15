from __future__ import annotations

from datetime import datetime, timezone

from conf.celery_app import celery_app
from schemas.search_schema import SearchRequest
from schemas.task_dispatch_schema import DispatchPayload, DispatchResult
from utils.exceptions import WorkflowError

QUEUE_BY_STAGE = {
    "search": "search_queue",
    "llm": "llm_queue",
    "export": "export_queue",
}


def build_enqueue_payload(task_id: str, request: SearchRequest) -> DispatchPayload:
    # 构造任务投递到异步队列时需要携带的基础元数据。
    return DispatchPayload(
        task_id=task_id,
        query=request.query,
        max_results=request.max_results,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        dispatch_version="v1",
    )


def get_queue_name(stage: str) -> str:
    # 根据处理阶段返回对应的 Celery 队列名。
    return QUEUE_BY_STAGE.get(stage, "search_queue")




async def dispatch_task(task_id: str, request: SearchRequest) -> DispatchResult:
    # 对外暴露统一的任务派发入口。
    return await dispatch_search_task(task_id, request)


async def dispatch_search_task(
    task_id: str,
    request: SearchRequest,
) -> DispatchResult:
    # 将搜索任务发送到 Celery 并返回派发结果摘要。
    enqueue_payload = build_enqueue_payload(task_id, request)
    queue_name = get_queue_name("search")
    try:
        result = celery_app.send_task(
            "tasks.run_search_task",
            kwargs={
                "task_id": task_id,
                "request_payload": request.model_dump(mode="json"),
            },
            queue=queue_name,
        )
    except WorkflowError:
        raise
    except Exception as exc:
        raise WorkflowError(
            f"任务派发失败，请检查 Celery/Redis 是否可用: {exc}",
            status_code=503,
        ) from exc

    return DispatchResult(
        accepted=True,
        task_id=task_id,
        dispatch_mode="celery",
        request_payload=enqueue_payload,
        queue=queue_name,
        celery_task_id=str(result.id),
    )
