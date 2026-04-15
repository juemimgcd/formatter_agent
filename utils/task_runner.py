from __future__ import annotations

import asyncio
from typing import Any

from conf.db_conf import AsyncSessionLocal
from schemas.search_schema import SearchRequest
from utils.task_service import run_search_task

_worker_loop: asyncio.AbstractEventLoop | None = None


def get_worker_event_loop() -> asyncio.AbstractEventLoop:
    # 为 Celery worker 复用同一个事件循环，避免 asyncpg 连接跨 loop 复用后失效。
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


async def execute_task_by_id(task_id: str, request: SearchRequest) -> None:
    # 在独立数据库会话中执行指定任务的完整搜索流程。
    async with AsyncSessionLocal.begin() as db:
        await run_search_task(task_id=task_id, request=request, db=db)


def execute_task_from_payload(task_id: str, request_payload: dict[str, Any]) -> None:
    # 将序列化请求载荷还原后同步触发异步任务执行。
    request = SearchRequest.model_validate(request_payload)
    get_worker_event_loop().run_until_complete(execute_task_by_id(task_id, request))
