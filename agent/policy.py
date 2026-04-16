from __future__ import annotations

from agent.state import AgentState, required_slots_filled
from schemas.agent_schema import AgentAction


def first_slot_with_status(state: AgentState, status: str) -> str | None:
    # 按 slots 当前顺序查找第一个指定状态的槽位。
    for field, slot_status in state.slots.items():
        if slot_status == status:
            return field
    return None


def build_slot_query(query: str, field: str) -> str:
    # 根据缺失槽位构造 targeted_search 使用的查询词。
    if field == "structured_results":
        return query
    return f"{query} {field}"


def decide_next_action(state: AgentState) -> AgentAction:
    # 集中根据当前 AgentState 决定下一步动作类型和动作参数。
    if state.done:
        return AgentAction(type="finalize", reason="state already done")

    conflict_field = first_slot_with_status(state, "conflict")
    if conflict_field:
        return AgentAction(
            type="verify",
            field=conflict_field,
            value=getattr(state.result, conflict_field, None),
            reason=f"{conflict_field} has conflicting evidence",
        )

    if required_slots_filled(state):
        return AgentAction(type="finalize", reason="required slots filled")

    if state.slots.get("candidates") == "missing":
        return AgentAction(
            type="search",
            query=state.query,
            reason="initial evidence collection",
        )

    missing_field = first_slot_with_status(state, "missing")
    if missing_field:
        return AgentAction(
            type="targeted_search",
            field=missing_field,
            query=build_slot_query(state.query, missing_field),
            reason=f"{missing_field} missing",
        )

    partial_field = first_slot_with_status(state, "partial")
    if partial_field:
        return AgentAction(
            type="targeted_search",
            field=partial_field,
            query=build_slot_query(state.query, partial_field),
            reason=f"{partial_field} only partially filled",
        )

    return AgentAction(type="finalize", reason="no actionable slot remains")
