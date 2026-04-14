from __future__ import annotations

from conf.db_conf import AsyncSessionLocal
from schemas import SearchRequest
from utils.task_service import run_search_task


async def execute_task_by_id(task_id: str, request: SearchRequest) -> None:
    """后台任务入口：在独立的 DB session 中执行一次搜索任务编排。"""
    async with AsyncSessionLocal.begin() as db:
        await run_search_task(task_id=task_id, request=request, db=db)
