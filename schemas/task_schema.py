from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from schemas.search_schema import StructuredResultItem


class TaskStatus(StrEnum):
    """任务状态枚举。"""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL_SUCCESS = "partial_success"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    EMPTY_RESULT = "empty_result"


class TaskItem(BaseModel):
    """任务统一返回模型。"""

    task_id: str
    query: str = ""
    status: TaskStatus = TaskStatus.CREATED
    total_items: int = 0
    excel_path: str | None = None
    preview_items: list[StructuredResultItem] = Field(default_factory=list)
    result_items: list[StructuredResultItem] = Field(default_factory=list)
    message: str = "任务已创建"
    error: str | None = None
    attempt_count: int = 0
    used_fallback: bool = False
    result_quality: str = "unknown"
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
    )
