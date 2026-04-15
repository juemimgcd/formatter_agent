from __future__ import annotations

import importlib.util
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
    return DispatchPayload(
        task_id=task_id,
        query=request.query,
        max_results=request.max_results,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        dispatch_version="v1",
    )


def get_queue_name(stage: str) -> str:
    return QUEUE_BY_STAGE.get(stage, "search_queue")


def ensure_broker_dependencies() -> None:
    broker_url = str(celery_app.conf.broker_url or "")
    if broker_url.startswith("redis://") and importlib.util.find_spec("redis") is None:
        raise WorkflowError(
            "Celery Redis 依赖未安装，请先执行 `uv sync` 或安装 `redis` 包",
            status_code=503,
        )


async def dispatch_task(task_id: str, request: SearchRequest) -> DispatchResult:
    return await dispatch_search_task(task_id, request)


async def dispatch_search_task(
    task_id: str,
    request: SearchRequest,
) -> DispatchResult:
    ensure_broker_dependencies()
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
