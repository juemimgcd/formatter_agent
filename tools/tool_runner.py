from __future__ import annotations

import asyncio
from urllib.parse import quote
from typing import Any

from conf.settings import settings
from schemas.agent_schema import AgentAction, ToolObservation
from schemas.search_schema import CandidateResultItem
from utils.excel_service import export_results_to_excel
from utils.exceptions import format_exception
from utils.retriever import build_rebuild_prompt_input
from utils.search_client import search_web
from utils.structured_result_builder import build_structured_results
from utils.task_service_helpers import (
    build_candidates,
    build_fallback_structured_items,
    evaluate_result_quality,
    filter_structured_items_by_candidates,
    select_top_candidates,
)

TOP_K = 5
REBUILD_SUMMARY_CHAR_LIMIT = 120


def build_llm_fallback_candidate(
    task_id: str,
    query: str,
    error_message: str,
) -> CandidateResultItem:
    # 搜索源全部失败时构造一个明确标记的本地知识候选，让后续 LLM 阶段继续产出结构化结果。
    return CandidateResultItem(
        candidate_id=f"{task_id}-llm-fallback",
        title=query,
        url=f"llm://local-knowledge/{quote(query, safe='')}",
        source="llm_local_knowledge",
        summary=(
            "联网搜索失败，后续结构化阶段将使用模型已有知识兜底。"
            f"搜索错误: {error_message}"
        ),
        extraction_notes=f"search_failed_fallback={error_message}",
        rerank_score=1.0,
    )


async def run_search_action(
    action: AgentAction,
    state,
    *,
    search_func=search_web,
    build_candidates_func=build_candidates,
    select_top_candidates_func=select_top_candidates,
) -> ToolObservation:
    # 执行通用搜索动作，并把原始搜索结果转换成候选结果。
    fetch_limit = max(TOP_K, state.max_results, settings.search_result_limit)
    try:
        search_results = await search_func(action.query, max_results=fetch_limit)
    except Exception as exc:
        error_message = format_exception(exc)
        if settings.search_failure_llm_fallback_enabled:
            fallback_candidate = build_llm_fallback_candidate(
                state.task_id,
                state.query,
                error_message,
            )
            return ToolObservation(
                type="search_result",
                raw_count=0,
                selected_count=1,
                candidates=[fallback_candidate],
                warnings=[
                    "web search failed; using llm local knowledge fallback",
                    error_message,
                ],
                summary=f"search failed, using llm fallback: {error_message}",
            )
        return ToolObservation(
            type="search_failed",
            error=error_message,
            summary=f"search failed: {error_message}",
        )

    search_warnings = [
        note
        for result in search_results
        for note in result.notes
        if note.startswith("search_warning=") or note.startswith("enrich_failed")
    ]
    raw_candidates = build_candidates_func(
        state.task_id,
        search_results,
        search_provider=settings.search_provider,
    )
    candidates = select_top_candidates_func(
        state.query,
        raw_candidates,
        top_k=TOP_K,
    )
    return ToolObservation(
        type="search_result",
        raw_count=len(raw_candidates),
        selected_count=len(candidates),
        candidates=candidates,
        warnings=search_warnings,
        summary=f"found {len(candidates)} candidates from {len(raw_candidates)} raw results",
    )


async def run_targeted_search_action(
    action: AgentAction,
    state,
    *,
    build_rebuild_prompt_input_func=build_rebuild_prompt_input,
    build_structured_results_func=build_structured_results,
    build_fallback_structured_items_func=build_fallback_structured_items,
    evaluate_result_quality_func=evaluate_result_quality,
    filter_structured_items_by_candidates_func=filter_structured_items_by_candidates,
) -> ToolObservation:
    # 执行补槽位动作，用已有候选结果生成结构化结果。
    candidates = list(state.result.candidates or [])
    if not candidates:
        quality = evaluate_result_quality_func([], used_fallback=False)
        return ToolObservation(
            type="structured_result",
            items=[],
            used_fallback=False,
            result_quality=quality.result_quality,
            warnings=quality.warnings,
            summary="skipped structured extraction because candidates are empty",
        )

    rebuilt_prompt_input_text = build_rebuild_prompt_input_func(
        state.query,
        candidates,
        max_items=TOP_K,
        max_summary_len=REBUILD_SUMMARY_CHAR_LIMIT,
    )

    extraction_warnings: list[str] = []
    used_fallback = False
    timeout_seconds = settings.structured_stage_timeout_seconds
    task = build_structured_results_func(
        query=state.query,
        rebuilt_prompt_input_text=rebuilt_prompt_input_text,
        max_output_items=state.max_results,
    )
    if timeout_seconds > 0:
        task = asyncio.wait_for(task, timeout=timeout_seconds)

    try:
        items = await task
    except Exception as exc:
        error_message = format_exception(exc)
        extraction_warnings.append(f"structured extraction fallback: {error_message}")
        items = build_fallback_structured_items_func(
            query=state.query,
            top_results=candidates,
            max_results=state.max_results,
        )
        used_fallback = True

    if items and not used_fallback:
        filter_check = filter_structured_items_by_candidates_func(
            state.query,
            items,
            candidates,
        )
        items = filter_check.items
        extraction_warnings.extend(filter_check.warnings)

    if not items:
        extraction_warnings.append("structured extraction returned empty result")
        items = build_fallback_structured_items_func(
            query=state.query,
            top_results=candidates,
            max_results=state.max_results,
        )
        used_fallback = True

    final_items = items[: state.max_results]
    quality = evaluate_result_quality_func(final_items, used_fallback=used_fallback)
    return ToolObservation(
        type="structured_result",
        items=final_items,
        used_fallback=used_fallback,
        result_quality=quality.result_quality,
        warnings=[*extraction_warnings, *quality.warnings],
        prompt_chars=len(rebuilt_prompt_input_text),
        summary=f"structured {len(final_items)} items via {'fallback' if used_fallback else 'llm'}",
    )


def run_verify_action(action: AgentAction, state) -> ToolObservation:
    # 执行轻量验证动作，当前版本只把冲突槽位标记为可接受。
    field = action.field
    return ToolObservation(
        type="verify_result",
        field=field,
        verified=True,
        summary=f"{field or 'field'} accepted by lightweight verifier",
    )


def run_finalize_action(
    state,
    *,
    export_results_to_excel_func=export_results_to_excel,
) -> ToolObservation:
    # 执行最终化动作，在存在结果时导出 Excel 文件。
    items = list(state.result.items or [])
    excel_path = export_results_to_excel_func(items) if items else None
    return ToolObservation(
        type="final_output",
        excel_path=excel_path,
        summary=f"finalized {len(items)} items",
    )


async def run_action(
    action: AgentAction,
    state,
    *,
    search_func=search_web,
    build_candidates_func=build_candidates,
    select_top_candidates_func=select_top_candidates,
    build_rebuild_prompt_input_func=build_rebuild_prompt_input,
    build_structured_results_func=build_structured_results,
    build_fallback_structured_items_func=build_fallback_structured_items,
    evaluate_result_quality_func=evaluate_result_quality,
    filter_structured_items_by_candidates_func=filter_structured_items_by_candidates,
    export_results_to_excel_func=export_results_to_excel,
) -> ToolObservation:
    # 根据 Policy 给出的 action type 分发到对应工具执行函数。
    action_type = action.type

    if action_type == "search":
        return await run_search_action(
            action,
            state,
            search_func=search_func,
            build_candidates_func=build_candidates_func,
            select_top_candidates_func=select_top_candidates_func,
        )
    if action_type == "targeted_search":
        return await run_targeted_search_action(
            action,
            state,
            build_rebuild_prompt_input_func=build_rebuild_prompt_input_func,
            build_structured_results_func=build_structured_results_func,
            build_fallback_structured_items_func=build_fallback_structured_items_func,
            evaluate_result_quality_func=evaluate_result_quality_func,
            filter_structured_items_by_candidates_func=filter_structured_items_by_candidates_func,
        )
    if action_type == "verify":
        return run_verify_action(action, state)
    if action_type == "finalize":
        return run_finalize_action(
            state,
            export_results_to_excel_func=export_results_to_excel_func,
        )

    return ToolObservation(
        type="unsupported_action",
        summary=f"unsupported action: {action_type}",
        warning=f"unsupported action: {action_type}",
    )
