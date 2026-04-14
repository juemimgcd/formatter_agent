from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from conf.db_conf import get_db
from crud import get_task_record_by_task_id
from schemas import SearchRequest, TaskItem
from utils.task_presenter import build_task_item_from_record
from utils.task_service import create_pending_task
from utils.task_runner import execute_task_by_id
from utils.response import success_response

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/search")
async def create_search_task(
    request: SearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = await create_pending_task(request, db)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="任务创建失败"
        )

    if db is not None:
        await db.commit()

    background_tasks.add_task(execute_task_by_id, task.task_id, request)

    return success_response(
        data=TaskItem.model_validate(task),
        status_code=202,
        background=background_tasks,
    )


@router.get("/{task_id}")
async def get_task_detail(task_id: str, db: AsyncSession = Depends(get_db)):
    record = await get_task_record_by_task_id(db, task_id=task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tasks not found"
        )
    return success_response(data=build_task_item_from_record(record))
