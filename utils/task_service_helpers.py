import re

from schemas import (
    CandidateResultItem,
    SearchResult,
    StructuredResultItem,
    TaskItem,
    TaskStatus,
)


def clean_text(value: str | None, default: str = "") -> str:
    """清洗文本并在为空时返回默认值。"""
    return (value or "").strip() or default


def extract_query_terms(query: str) -> list[str]:
    """把 query 规范化为可用于匹配打分的词项列表。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", clean_text(query).lower()).split()


def score_search_result(query: str, result: SearchResult) -> float:
    """根据排序位置和关键词覆盖率计算结果分数。"""
    terms = list(dict.fromkeys(extract_query_terms(query)))
    haystack = f"{result.title} {result.snippet}".lower()
    coverage = sum(term in haystack for term in terms) / len(terms) if terms else 0.0
    rank_score = max(0.25, 1.0 - (max(1, result.rank) - 1) * 0.08)
    return round(min(0.6 * rank_score + 0.4 * coverage, 0.99), 4)


def build_fallback_structured_items(
    *,
    query: str,
    top_results: list[CandidateResultItem],
    max_results: int,
) -> list[StructuredResultItem]:
    """把候选结果直接降级映射成结构化结果。"""
    return [
        StructuredResultItem(
            query=query,
            title=clean_text(row.title, "未命名结果"),
            source=clean_text(row.source, "unknown"),
            url=clean_text(row.url),
            content_type="unknown",
            region="不限",
            role_direction="通用",
            summary=clean_text(row.summary),
            quality_score=max(0, min(int((row.rerank_score or 0.0) * 100), 100)),
            extraction_notes=clean_text(
                row.extraction_notes,
                "fallback_from_results_due_to_structured_timeout",
            ),
        )
        for row in top_results[:max_results]
    ]


def select_top_k_results(
    query: str,
    search_results: list[SearchResult],
    *,
    top_k: int,
) -> list[SearchResult]:
    """按启发式分数排序并截断到固定 top-k。"""
    return sorted(
        search_results,
        key=lambda result: score_search_result(query, result),
        reverse=True,
    )[:top_k]


def build_candidates(
    task_id: str,
    query: str,
    search_results: list[SearchResult],
    *,
    search_provider: str,
) -> list[CandidateResultItem]:
    """把搜索结果转换成后续结构化阶段使用的候选列表。"""
    candidates: list[CandidateResultItem] = []
    for index, result in enumerate(search_results):
        title = clean_text(result.title)
        url = clean_text(result.url)
        if not title or not url:
            continue

        candidates.append(
            CandidateResultItem(
                candidate_id=f"{task_id}_{index}",
                title=title,
                url=url,
                source=clean_text(result.source, "web"),
                summary=clean_text(result.snippet, title),
                extraction_notes=(
                    f"search_provider={search_provider};"
                    f"search_rank={max(1, int(result.rank or index + 1))}"
                ),
                rerank_score=float(score_search_result(query, result)),
            )
        )

    return candidates


def build_result_payload(
    items: list[StructuredResultItem],
    excel_path: str | None = None,
) -> dict:
    """把结构化结果打包成可持久化的 payload。"""
    return {
        "result_count": len(items),
        "excel_path": excel_path,
        "result_payload": [item.model_dump(mode="json") for item in items],
        "error_message": None,
    }


def build_task_item(
    *,
    task_id: str,
    query: str,
    status: TaskStatus,
    message: str,
    result_items: list[StructuredResultItem] | None = None,
    excel_path: str | None = None,
    error: str | None = None,
    preview_limit: int = 3,
) -> TaskItem:
    """统一构造接口层使用的 TaskItem。"""
    items = result_items if result_items is not None else []
    return TaskItem(
        task_id=task_id,
        query=query,
        status=status,
        total_items=len(items),
        excel_path=excel_path,
        preview_items=items[:preview_limit],
        result_items=items,
        message=message,
        error=error,
    )
