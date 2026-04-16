from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from schemas.search_schema import CandidateResultItem, SearchResult, StructuredResultItem
from schemas.task_schema import TaskItem, TaskStatus

MIN_RELEVANCE_SCORE = 0.5
GENERIC_CJK_CHARS = set("作品大全全集列表资料信息相关关于查询搜索内容网页结果")


def clean_text(value: str) -> str:
    # 清洗文本中的首尾空白和多余空格。
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_candidate_url(url: str) -> str:
    # 统一规范 URL 形式并移除尾部斜杠。
    return clean_text(url).rstrip("/")


def extract_candidate_source(url: str, fallback: str = "") -> str:
    # 从 URL 中提取来源域名，并在缺失时使用兜底来源。
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or clean_text(fallback) or "unknown"


def build_candidates(
    task_id: str,
    search_results: list[SearchResult],
    *,
    search_provider: str,
) -> list[CandidateResultItem]:
    # 将搜索结果转换为后续重排和结构化阶段使用的候选项。
    candidates: list[CandidateResultItem] = []
    for index, item in enumerate(search_results, start=1):
        title = clean_text(item.title)
        url = normalize_candidate_url(item.url)
        if not title or not url:
            continue

        candidates.append(
            CandidateResultItem(
                candidate_id=f"{task_id}-{index:02d}",
                title=title,
                url=url,
                source=extract_candidate_source(url, item.source or search_provider),
                summary=clean_text(item.snippet),
                page_excerpt=clean_text(item.page_excerpt),
                extraction_notes=clean_text(
                    "; ".join(
                        [
                            f"provider={item.provider or search_provider}",
                            f"provider_rank={item.provider_rank or item.rank}",
                            f"rank={item.rank}",
                            f"score={item.final_score:.4f}",
                            *item.notes,
                        ]
                    )
                ),
                rerank_score=(
                    item.final_score
                    if item.final_score > 0
                    else max(0.0, float(len(search_results) - index + 1))
                ),
            )
        )

    return candidates


def build_fallback_structured_items(
    *,
    query: str,
    top_results: list[CandidateResultItem],
    max_results: int,
) -> list[StructuredResultItem]:
    # 在结构化抽取失败时用候选结果生成保底结构化结果。
    fallback_items: list[StructuredResultItem] = []
    for index, item in enumerate(top_results[:max_results], start=1):
        summary = (
            clean_text(item.summary)
            or clean_text(item.page_excerpt)
            or clean_text(item.extraction_notes)
        )
        fallback_items.append(
            StructuredResultItem(
                query=query,
                title=clean_text(item.title) or "未命名结果",
                source=clean_text(item.source) or "unknown",
                url=normalize_candidate_url(item.url),
                content_type="unknown",
                region="不限",
                role_direction="通用",
                summary=summary,
                quality_score=max(40, 90 - (index - 1) * 10),
                extraction_notes=clean_text(item.extraction_notes),
            )
        )

    return fallback_items


def build_result_payload(
    result_items: list[StructuredResultItem],
    excel_path: str | None = None,
    error_message: str | None = None,
) -> dict:
    # 构造写回任务记录的结果载荷字典。
    payload: dict = {
        "result_count": len(result_items),
        "excel_path": excel_path,
        "result_payload": [item.model_dump(mode="json") for item in result_items],
    }
    if error_message is not None:
        payload["error_message"] = error_message
    return payload


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
    used_fallback: bool = False,
    result_quality: str = "unknown",
    warnings: list[str] | None = None,
) -> TaskItem:
    # 组装接口层统一使用的任务返回对象。
    normalized_items = result_items or []
    return TaskItem(
        task_id=task_id,
        query=query,
        status=status,
        total_items=len(normalized_items),
        excel_path=excel_path,
        preview_items=normalized_items[:preview_limit],
        result_items=normalized_items,
        message=message,
        error=error,
        used_fallback=used_fallback,
        result_quality=result_quality,
        warnings=warnings or [],
    )


class ResultQualityCheck(BaseModel):
    result_quality: str = "unknown"
    warnings: list[str] = Field(default_factory=list)


class StructuredResultFilterCheck(BaseModel):
    items: list[StructuredResultItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def average_result_quality(items: list[StructuredResultItem]) -> float:
    # 计算结构化结果的平均质量分，空列表按 0 分处理。
    if not items:
        return 0.0
    return sum(item.quality_score for item in items) / len(items)


def evaluate_result_quality(
    items: list[StructuredResultItem],
    *,
    used_fallback: bool,
) -> ResultQualityCheck:
    # 给最终结果做轻量质量标注，不触发自动重试或额外模型调用。
    if not items:
        return ResultQualityCheck(
            result_quality="low",
            warnings=["structured result is empty"],
        )

    if used_fallback:
        return ResultQualityCheck(
            result_quality="fallback",
            warnings=["structured result was generated by fallback path"],
        )

    warnings: list[str] = []
    if average_result_quality(items) < 50:
        warnings.append("average quality_score is below 50")
    if any(not item.url for item in items):
        warnings.append("some structured items have empty url")

    if warnings:
        return ResultQualityCheck(result_quality="low", warnings=warnings)

    return ResultQualityCheck(result_quality="high")


def extract_query_terms(query: str) -> list[str]:
    # 提取英文、数字和空格分隔词，用于常规关键词匹配。
    return [term for term in clean_text(query).lower().split(" ") if term]


def extract_significant_cjk_chars(value: str) -> set[str]:
    # 提取中文查询中的关键字，过滤“大全/全集/列表”等泛化描述词。
    chars: set[str] = set()
    for char in clean_text(value):
        if "\u4e00" <= char <= "\u9fff" and char not in GENERIC_CJK_CHARS:
            chars.add(char)
    return chars


def calculate_text_relevance(query: str, text: str) -> float:
    # 计算 query 与候选文本之间的轻量相关性，兼容无空格中文查询。
    normalized_query = clean_text(query).lower()
    haystack = clean_text(text).lower()
    if not normalized_query or not haystack:
        return 0.0

    terms = extract_query_terms(normalized_query)
    term_score = 0.0
    if terms:
        matches = sum(term in haystack for term in terms)
        term_score = matches / len(terms)

    query_chars = extract_significant_cjk_chars(normalized_query)
    cjk_score = 0.0
    if query_chars:
        haystack_chars = extract_significant_cjk_chars(haystack)
        cjk_score = len(query_chars & haystack_chars) / len(query_chars)

    return round(max(term_score, cjk_score), 4)


def deduplicate_candidates(items: list[CandidateResultItem]) -> list[CandidateResultItem]:
    # 按 URL 去重候选结果并统一保留规范化后的链接。
    deduplicated: list[CandidateResultItem] = []
    seen_urls: set[str] = set()
    for item in items:
        normalized_url = normalize_candidate_url(item.url)
        if not normalized_url or normalized_url in seen_urls:
            continue
        deduplicated.append(item.model_copy(update={"url": normalized_url}))
        seen_urls.add(normalized_url)
    return deduplicated


def score_candidate(query: str, item: CandidateResultItem) -> float:
    # 根据查询词命中情况为候选结果计算一个简单相关性分数。
    haystack = f"{item.title} {item.summary} {item.page_excerpt}"
    return calculate_text_relevance(query, haystack)


def select_top_candidates(
    query: str,
    items: list[CandidateResultItem],
    *,
    top_k: int,
) -> list[CandidateResultItem]:
    # 对候选结果按相关性排序后截取前 top_k 条。
    scored_items = [
        (item, score_candidate(query, item)) for item in deduplicate_candidates(items)
    ]
    relevant_items = [
        (item, score)
        for item, score in scored_items
        if score >= MIN_RELEVANCE_SCORE
    ]
    ranked = sorted(
        relevant_items,
        key=lambda item_and_score: (
            item_and_score[1],
            item_and_score[0].rerank_score or 0.0,
        ),
        reverse=True,
    )
    return [item for item, score in ranked[:top_k]]


def filter_structured_items_by_candidates(
    query: str,
    items: list[StructuredResultItem],
    candidates: list[CandidateResultItem],
) -> StructuredResultFilterCheck:
    # 过滤 LLM 输出，确保最终结果来自候选 URL，避免模型编造不相关结果。
    candidate_by_url = {
        normalize_candidate_url(candidate.url): candidate for candidate in candidates
    }
    filtered_items: list[StructuredResultItem] = []
    warnings: list[str] = []

    for item in items:
        normalized_url = normalize_candidate_url(item.url)
        candidate = candidate_by_url.get(normalized_url)
        if candidate is None:
            warnings.append(f"drop structured item with unknown url: {item.title}")
            continue

        candidate_text = f"{candidate.title} {candidate.summary} {candidate.page_excerpt}"
        candidate_score = calculate_text_relevance(query, candidate_text)
        item_text = f"{item.title} {item.summary}"
        item_score = calculate_text_relevance(query, item_text)
        if max(candidate_score, item_score) < MIN_RELEVANCE_SCORE:
            warnings.append(f"drop low relevance structured item: {item.title}")
            continue

        filtered_items.append(item)

    return StructuredResultFilterCheck(items=filtered_items, warnings=warnings)
