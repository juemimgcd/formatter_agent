from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from models.task_record import TaskRecord
from models.task_record import TaskRecord
from schemas.task_schema import TaskStatus


async def create_task_record(db: AsyncSession, payload: dict):
    """创建任务记录并返回统一任务对象。"""

    record = TaskRecord(
        task_id=payload.get("task_id", ""),
        query=payload.get("query", ""),
        status=str(payload.get("status", TaskStatus.CREATED)),
        result_count=payload.get("result_count", 0),
        excel_path=payload.get("excel_path"),
        result_payload=payload.get("result_payload"),
        error_message=payload.get("error_message"),
    )

    db.add(record)
    await db.flush()
    return record


async def get_task_record_by_task_id(db: AsyncSession, task_id: str):
    stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_task_record_status(
    db: AsyncSession,
    task_id: str,
    status: str,
    extra_data: dict | None = None,
):
    """更新任务状态并返回统一任务对象。"""

    record = await get_task_record_by_task_id(db, task_id)
    if not record:
        return None

    record.status = str(status)
    if extra_data:
        if "result_count" in extra_data:
            record.result_count = int(extra_data["result_count"])
        if "excel_path" in extra_data:
            record.excel_path = extra_data["excel_path"]
        if "result_payload" in extra_data:
            record.result_payload = extra_data["result_payload"]
        if "error_message" in extra_data:
            record.error_message = extra_data["error_message"]

    await db.flush()
    return record





def build_task_query_filters(
    *,
    status: str | None,
    query: str | None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(TaskRecord.status == status)
    if query:
        filters.append(
            or_(
                TaskRecord.query.ilike(f"%{query}%"),
                TaskRecord.task_id.ilike(f"%{query}%"),
            )
        )
    return filters


async def list_task_records(
    db: AsyncSession,
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[TaskRecord]:
    stmt = (
        select(TaskRecord)
        .where(*build_task_query_filters(status=status, query=query))
        .order_by(desc(TaskRecord.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())