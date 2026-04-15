from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from conf.db_conf import get_db
from crud import get_task_record_by_task_id, update_task_record_status
from schemas.search_schema import SearchRequest
from schemas.task_schema import TaskItem, TaskStatus
from utils.response import success_response
from utils.task_dispatcher import dispatch_task
from utils.task_presenter import build_task_item_from_record
from utils.task_service import create_pending_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/search")
async def create_search_task(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    task = await create_pending_task(request, db)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="任务创建失败"
        )

    if db is not None:
        await db.commit()

    dispatch_result = await dispatch_task(task.task_id, request)
    if not dispatch_result.accepted:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务派发失败",
        )

    queued_task = TaskItem.model_validate(task).model_copy(
        update={
            "status": TaskStatus.QUEUED,
            "message": "任务已排队",
        }
    )

    if db is not None:
        await update_task_record_status(db, task.task_id, TaskStatus.QUEUED)
        await db.commit()

    return success_response(data=queued_task, status_code=202)


@router.get("/{task_id}")
async def get_task_detail(task_id: str, db: AsyncSession = Depends(get_db)):
    record = await get_task_record_by_task_id(db, task_id=task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tasks not found"
        )
    return success_response(data=build_task_item_from_record(record))
