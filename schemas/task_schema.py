from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    """任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SearchRequest(BaseModel):
    """用户提交搜索任务时的最小输入。"""

    query: str = Field(..., min_length=1, max_length=200, description="搜索主题")
    max_results: int = Field(default=5, ge=1, le=50, description="保留的最大结果数")


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str
    rank: int


class CandidateResultItem(BaseModel):
    """search top-k 结果的统一结构。"""

    candidate_id: str
    title: str
    url: str
    source: str = ""
    summary: str = ""
    extraction_notes: str = ""
    rerank_score: float = 0.0


class StructuredResultItem(BaseModel):
    """最终用于预览和导出的结构化结果。"""

    query: str
    title: str
    source: str
    url: str
    content_type: str = "unknown"
    region: str = "不限"
    role_direction: str = "通用"
    summary: str = ""
    quality_score: int = Field(default=60, ge=0, le=100)
    extraction_notes: str = ""


class StructuredResultSet(BaseModel):
    """第二段 LLM 的结构化结果列表包装。"""

    items: list[StructuredResultItem] = Field(default_factory=list)


class TaskItem(BaseModel):
    """任务统一返回模型。"""

    task_id: str
    query: str = ""
    status: TaskStatus = TaskStatus.PENDING
    total_items: int = 0
    excel_path: str | None = None
    preview_items: list[StructuredResultItem] = Field(default_factory=list)
    result_items: list[StructuredResultItem] = Field(default_factory=list)
    message: str = "任务已创建"
    error: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )
