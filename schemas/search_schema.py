from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """用户提交搜索任务时的最小输入。"""

    query: str = Field(..., min_length=1, max_length=200, description="搜索主题")
    max_results: int = Field(default=5, ge=1, le=50, description="保留的最大结果数")


class SearchResult(BaseModel):
    """统一搜索候选结果。

    基础字段保持向后兼容；额外字段用于 search pipeline 的归一化、
    多特征重排和正文增强。
    """

    title: str
    url: str
    snippet: str
    source: str
    rank: int
    provider: str = ""
    provider_rank: int = 0
    normalized_url: str = ""
    lexical_score: float = 0.0
    intent_pattern_score: float = 0.0
    source_score: float = 0.0
    provider_rank_score: float = 0.0
    final_score: float = 0.0
    page_excerpt: str = ""
    notes: list[str] = Field(default_factory=list)


class CandidateResultItem(BaseModel):
    """search top-k 结果的统一结构。"""

    candidate_id: str
    title: str
    url: str
    source: str = ""
    summary: str = ""
    page_excerpt: str = ""
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
