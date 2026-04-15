from __future__ import annotations

import json
from typing import Any

from schemas.search_schema import CandidateResultItem


RebuildPromptPayload = dict[str, Any]


def trim_text(text: str, limit: int) -> str:
    """裁剪文本长度并在超长时追加省略号。"""
    # 将文本裁剪到指定长度以内并保持输出可读。
    merged = text.strip()
    if limit <= 0:
        return merged
    if len(merged) <= limit:
        return merged
    return f"{merged[:limit].rstrip()}..."


def build_rebuild_prompt_payload(
    query: str,
    top_candidates: list[CandidateResultItem],
    *,
    max_items: int = 12,
    max_summary_len: int = 180,
) -> RebuildPromptPayload:
    """构造二阶段结构化抽取所需的 JSON payload（Python dict 形式）。

    该 payload 会把 top-k 候选结果压缩成稳定字段集合，并进行：
    - 过滤空 URL；
    - 标题/来源默认值填充；
    - summary / extraction_notes 截断；
    - 保留 rerank score 便于 LLM 做排序参考。
    """
    # 把候选搜索结果整理成二阶段结构化抽取使用的稳定输入数据。
    results: list[dict[str, Any]] = []
    for item in top_candidates[:max_items]:
        url = (item.url or "").strip()
        if not url:
            continue

        results.append(
            {
                "candidate_id": item.candidate_id,
                "title": (item.title or "").strip() or "未命名结果",
                "url": url,
                "source": (item.source or "").strip() or "unknown",
                "content_type": "unknown",
                "region": "不限",
                "role_direction": "通用",
                "summary": trim_text(item.summary, max_summary_len),
                "score": item.rerank_score or 0.0,
                "extraction_notes": trim_text(item.extraction_notes, 240),
            }
        )

    return {"query": query, "top_candidates": results}


def build_rebuild_prompt_input(
    query: str,
    top_candidates: list[CandidateResultItem],
    *,
    max_items: int = 12,
    max_summary_len: int = 180,
) -> str:
    """将 `build_rebuild_prompt_payload` 的结果序列化为可读 JSON 文本。

    返回值会用于传入二阶段 LLM（结构化抽取）作为上下文输入。
    """
    # 将重建后的提示词载荷序列化成可直接传给 LLM 的 JSON 文本。
    payload = build_rebuild_prompt_payload(
        query,
        top_candidates,
        max_items=max_items,
        max_summary_len=max_summary_len,
    )
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)
