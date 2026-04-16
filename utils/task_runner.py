from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from conf.db_conf import AsyncSessionLocal
from conf.logging_conf import app_logger
from conf.settings import settings
from crud import get_task_record_by_task_id, update_task_record_status
from schemas.search_schema import SearchRequest
from schemas.task_dispatch_schema import DispatchPayload
from schemas.task_schema import TaskStatus
from utils.task_service import run_search_task
from utils.task_service_helpers import build_result_payload

logger = app_logger.bind(module="task_runner")
RUNNABLE_TASK_STATUSES = {
    str(TaskStatus.CREATED),
    str(TaskStatus.QUEUED),
    str(TaskStatus.RETRYING),
}

_worker_loop: asyncio.AbstractEventLoop | None = None


def parse_dispatch_submitted_at(value: str) -> datetime | None:
    # 解析任务投递时间，解析失败时返回 None 交给调用方跳过旧消息。
    try:
        normalized_value = value.replace("Z", "+00:00")
        submitted_at = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None

    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    return submitted_at.astimezone(timezone.utc)


def get_dispatch_skip_reason(dispatch_payload: DispatchPayload | None) -> str | None:
    # 判断 Celery 消息是否缺少派发元数据或已经超过允许执行窗口。
    if dispatch_payload is None:
        return "任务消息缺少派发元数据，疑似旧队列残留，已跳过执行"

    expires_seconds = settings.celery_task_expires_seconds
    if expires_seconds <= 0:
        return None

    submitted_at = parse_dispatch_submitted_at(dispatch_payload.submitted_at)
    if submitted_at is None:
        return "任务消息派发时间格式无效，已跳过执行"

    age_seconds = (datetime.now(timezone.utc) - submitted_at).total_seconds()
    if age_seconds > expires_seconds:
        return (
            f"任务消息已过期，已跳过执行: age_seconds={age_seconds:.1f}, "
            f"expires_seconds={expires_seconds}"
        )
    return None


def get_worker_event_loop() -> asyncio.AbstractEventLoop:
    # 为 Celery worker 复用同一个事件循环，避免 asyncpg 连接跨 loop 复用后失效。
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


async def execute_task_by_id(
    task_id: str,
    request: SearchRequest,
    dispatch_payload: DispatchPayload | None = None,
) -> None:
    # 在真正执行前检查 DB 状态和消息年龄，避免旧队列消息启动后自动重跑。
    async with AsyncSessionLocal.begin() as db:
        record = await get_task_record_by_task_id(db, task_id=task_id)
        if record is None:
            logger.warning("task={} stage=worker_skip reason=record_not_found", task_id)
            return

        current_status = str(getattr(record, "status", ""))
        if current_status not in RUNNABLE_TASK_STATUSES:
            logger.warning(
                "task={} stage=worker_skip reason=status_not_runnable status={}",
                task_id,
                current_status,
            )
            return

        skip_reason = get_dispatch_skip_reason(dispatch_payload)
        if skip_reason:
            logger.warning(
                "task={} stage=worker_skip reason={}",
                task_id,
                skip_reason,
            )
            await update_task_record_status(
                db,
                task_id,
                TaskStatus.TIMEOUT,
                extra_data=build_result_payload([], error_message=skip_reason),
            )
            return

        await run_search_task(task_id=task_id, request=request, db=db)


def parse_dispatch_payload(
    dispatch_payload: dict[str, Any] | None,
) -> DispatchPayload | None:
    # 将 Celery 消息里的派发元数据还原成 schema，缺失或非法时按旧消息处理。
    if dispatch_payload is None:
        return None
    try:
        return DispatchPayload.model_validate(dispatch_payload)
    except Exception:
        return None


def execute_task_from_payload(
    task_id: str,
    request_payload: dict[str, Any],
    dispatch_payload: dict[str, Any] | None = None,
) -> None:
    # 将序列化请求载荷还原后同步触发异步任务执行。
    request = SearchRequest.model_validate(request_payload)
    parsed_dispatch_payload = parse_dispatch_payload(dispatch_payload)
    get_worker_event_loop().run_until_complete(
        execute_task_by_id(task_id, request, parsed_dispatch_payload)
    )
