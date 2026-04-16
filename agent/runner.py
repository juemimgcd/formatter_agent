from __future__ import annotations

from typing import Any

from agent.compiler import compile_task
from agent.finalizer import build_output
from agent.policy import decide_next_action
from agent.reducer import reduce_state
from schemas.agent_schema import AgentOutput
from schemas.registry import resolve_output_schema
from tools.tool_runner import run_action
from utils.intent_parser import parse_search_intent
from utils.excel_service import export_results_to_excel
from utils.retriever import build_rebuild_prompt_input
from utils.search_client import search_web
from utils.structured_result_builder import build_structured_results
from utils.task_service_helpers import (
    build_candidates,
    build_fallback_structured_items,
    evaluate_result_quality,
    select_top_candidates,
)


async def run_agent(
    query: str,
    *,
    task_id: str = "",
    max_results: int = 5,
    max_rounds: int = 4,
    parse_intent_func=parse_search_intent,
    resolve_schema_func=resolve_output_schema,
    search_func=search_web,
    build_candidates_func=build_candidates,
    select_top_candidates_func=select_top_candidates,
    build_rebuild_prompt_input_func=build_rebuild_prompt_input,
    build_structured_results_func=build_structured_results,
    build_fallback_structured_items_func=build_fallback_structured_items,
    evaluate_result_quality_func=evaluate_result_quality,
    export_results_to_excel_func=export_results_to_excel,
) -> AgentOutput:
    # 运行显式 Agent Loop：编译任务、决策动作、执行工具、归约状态并最终输出。
    state = compile_task(
        query,
        task_id=task_id,
        max_results=max_results,
        max_rounds=max_rounds,
        parse_intent=parse_intent_func,
        resolve_schema=resolve_schema_func,
    )

    while not state.done and state.round_idx < state.max_rounds:
        action = decide_next_action(state)
        observation = await run_action(
            action,
            state,
            search_func=search_func,
            build_candidates_func=build_candidates_func,
            select_top_candidates_func=select_top_candidates_func,
            build_rebuild_prompt_input_func=build_rebuild_prompt_input_func,
            build_structured_results_func=build_structured_results_func,
            build_fallback_structured_items_func=build_fallback_structured_items_func,
            evaluate_result_quality_func=evaluate_result_quality_func,
            export_results_to_excel_func=export_results_to_excel_func,
        )
        state = reduce_state(state, action, observation)
        state.round_idx += 1

    if not state.done:
        state.done = True
        state.stop_reason = "round_budget_exhausted"
        state.warnings.append("round budget exhausted before finalize action")

    return build_output(state)
