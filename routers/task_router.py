from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from conf.settings import settings
from conf.db_conf import get_db
from crud import (
    get_task_record_by_task_id,
    list_task_records,
    update_task_record_status,
)
from schemas.search_schema import SearchRequest
from schemas.task_schema import TaskItem, TaskStatus
from utils.response import success_response
from utils.task_dispatcher import dispatch_task
from utils.task_control_service import can_cancel, can_retry
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


@router.get("")
async def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    records = await list_task_records(
        db,
        status=str(status_filter) if status_filter else None,
        query=query,
        limit=limit,
        offset=offset,
    )
    items = [build_task_item_from_record(record) for record in records]
    return success_response(
        data={
            "items": items,
            "count": len(items),
            "limit": limit,
            "offset": offset,
        }
    )


@router.get("/{task_id}")
async def get_task_detail(task_id: str, db: AsyncSession = Depends(get_db)):
    record = await get_task_record_by_task_id(db, task_id=task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tasks not found"
        )
    return success_response(data=build_task_item_from_record(record))


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db)):
    record = await get_task_record_by_task_id(db, task_id=task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tasks not found"
        )

    if not can_cancel(getattr(record, "status", "")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前任务状态不允许取消",
        )

    updated = await update_task_record_status(db, task_id, TaskStatus.CANCELLED)
    if db is not None:
        await db.commit()

    task_item = build_task_item_from_record(updated or record).model_copy(
        update={
            "status": TaskStatus.CANCELLED,
            "message": "任务已取消",
            "warnings": ["当前取消通过任务状态检查点生效，尚未向 Celery worker 发送强制 revoke 指令。"],
        }
    )
    return success_response(data=task_item)


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    max_results: int = Query(
        default=settings.search_result_limit,
        ge=1,
        le=50,
        description="重试时重新请求的最大结果数；当前系统未持久化原始 max_results，因此这里允许显式指定。",
    ),
    db: AsyncSession = Depends(get_db),
):
    record = await get_task_record_by_task_id(db, task_id=task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tasks not found"
        )

    current_status = getattr(record, "status", "")
    if not can_retry(current_status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前任务状态不允许重试",
        )

    retry_request = SearchRequest(query=record.query, max_results=max_results)
    dispatch_result = await dispatch_task(task_id, retry_request)
    if not dispatch_result.accepted:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务派发失败",
        )

    updated = await update_task_record_status(
        db,
        task_id,
        TaskStatus.QUEUED,
        extra_data={
            "result_count": 0,
            "excel_path": None,
            "result_payload": [],
            "error_message": None,
        },
    )
    if db is not None:
        await db.commit()

    task_item = build_task_item_from_record(updated or record).model_copy(
        update={
            "status": TaskStatus.QUEUED,
            "total_items": 0,
            "preview_items": [],
            "result_items": [],
            "excel_path": None,
            "error": None,
            "message": "任务已重新排队",
        }
    )
    return success_response(data=task_item, status_code=202)
