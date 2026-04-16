from __future__ import annotations

from typing import Any

from agent.state import ActionTrace, AgentState, Evidence
from schemas.agent_schema import AgentAction, ToolObservation
from schemas.search_schema import CandidateResultItem, StructuredResultItem


def append_action_trace(
    state: AgentState,
    action: AgentAction,
    observation: ToolObservation,
) -> None:
    # 把本轮 action 与 observation 摘要写入可解释执行轨迹。
    params = {
        key: value
        for key, value in action.model_dump(exclude_none=True).items()
        if key not in {"type", "reason"} and value != ""
    }
    state.trace.append(
        ActionTrace(
            round_idx=state.round_idx,
            action_type=action.type,
            params=params,
            reason=action.reason,
            summary=observation.summary,
        )
    )


def build_candidate_evidence(item: CandidateResultItem) -> Evidence:
    # 将搜索候选结果转换成 state.evidence 中的证据条目。
    return Evidence(
        field="candidates",
        value={"title": item.title, "url": item.url},
        source=item.source or "web",
        confidence=max(0.1, min(1.0, float(item.rerank_score or 0.0))),
        note=item.extraction_notes,
    )


def build_structured_evidence(item: StructuredResultItem) -> Evidence:
    # 将结构化结果转换成 state.evidence 中的证据条目。
    return Evidence(
        field="structured_results",
        value=item.model_dump(mode="json"),
        source=item.source or "structured_extraction",
        confidence=max(0.0, min(1.0, item.quality_score / 100)),
        note=item.extraction_notes,
    )


def reduce_state(
    state: AgentState,
    action: AgentAction,
    observation: ToolObservation,
) -> AgentState:
    # 根据工具 observation 更新 slots、result、evidence、warnings 和 done 标记。
    append_action_trace(state, action, observation)
    observation_type = observation.type

    if observation_type == "search_result":
        candidates = list(observation.candidates)
        state.result.raw_result_count = observation.raw_count
        state.result.selected_candidate_count = observation.selected_count
        state.result.candidates = candidates
        state.slots["candidates"] = "filled"
        state.evidence.extend(build_candidate_evidence(item) for item in candidates)
        for warning in observation.warnings:
            if warning not in state.warnings:
                state.warnings.append(warning)
        if not candidates:
            state.slots["structured_results"] = "filled"
            state.result.items = []
            state.result.used_fallback = False
            state.result.result_quality = "low"
            state.warnings.append("structured result is empty")
        return state

    if observation_type == "search_failed":
        state.result.error = observation.error or "search failed"
        state.result.items = []
        state.done = True
        state.stop_reason = "search_failed"
        state.warnings.append(str(state.result.error))
        return state

    if observation_type == "structured_result":
        items = list(observation.items)
        state.result.items = items
        state.result.structured_result_count = len(items)
        state.result.used_fallback = observation.used_fallback
        state.result.result_quality = observation.result_quality
        state.slots["structured_results"] = "filled"
        state.evidence.extend(build_structured_evidence(item) for item in items)
        for warning in observation.warnings:
            if warning not in state.warnings:
                state.warnings.append(warning)
        return state

    if observation_type == "verify_result":
        field = observation.field
        if field:
            state.slots[str(field)] = "filled"
        return state

    if observation_type == "final_output":
        state.result.excel_path = observation.excel_path
        state.done = True
        state.stop_reason = "required_slots_filled"
        return state

    if observation.warning:
        state.warnings.append(str(observation.warning))
    return state
