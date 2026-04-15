from __future__ import annotations

import asyncio
from typing import Any

from conf.db_conf import AsyncSessionLocal
from schemas.search_schema import SearchRequest
from utils.task_service import run_search_task


async def execute_task_by_id(task_id: str, request: SearchRequest) -> None:
    async with AsyncSessionLocal.begin() as db:
        await run_search_task(task_id=task_id, request=request, db=db)


def execute_task_from_payload(task_id: str, request_payload: dict[str, Any]) -> None:
    request = SearchRequest.model_validate(request_payload)
    asyncio.run(execute_task_by_id(task_id, request))
