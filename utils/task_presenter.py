from __future__ import annotations

from models.task_record import TaskRecord
from schemas.search_schema import StructuredResultItem
from schemas.task_schema import TaskItem, TaskStatus


def parse_task_status(value: str) -> TaskStatus:
    """将数据库中的状态字符串解析为 `TaskStatus`。

    解析失败时返回 `TaskStatus.FAILED`，避免接口层因为脏数据崩溃。
    """
    try:
        return TaskStatus(value)
    except Exception:
        return TaskStatus.FAILED


def build_structured_items_from_payload(
    payload: list[dict] | None,
) -> list[StructuredResultItem]:
    """将持久化的 result_payload（list[dict]）反序列化为结构化结果对象列表。"""
    if not payload:
        return []

    items: list[StructuredResultItem] = []
    for row in payload:
        try:
            items.append(StructuredResultItem.model_validate(row))
        except Exception:
            continue
    return items


def build_task_item_from_record(record: TaskRecord) -> TaskItem:
    """把 `TaskRecord` 转换为对外接口使用的 `TaskItem`。

    - 解析状态枚举
    - 恢复结构化结果列表
    - 生成 preview_items 与 message
    """
    status = parse_task_status(getattr(record, "status", ""))
    result_items = build_structured_items_from_payload(record.result_payload)
    total_items = int(record.result_count or 0)
    if status == TaskStatus.SUCCESS:
        message = "任务执行完成" if total_items > 0 else "未找到可用结果"
    else:
        message = {
            TaskStatus.CREATED: "任务已创建",
            TaskStatus.QUEUED: "任务已排队",
            TaskStatus.RUNNING: "任务执行中",
            TaskStatus.FAILED: "任务失败",
        }.get(status, "ok")

    return TaskItem(
        task_id=record.task_id,
        query=record.query,
        status=status,
        total_items=total_items,
        excel_path=record.excel_path,
        preview_items=result_items[:3],
        result_items=result_items,
        message=message,
        error=record.error_message,
    )
