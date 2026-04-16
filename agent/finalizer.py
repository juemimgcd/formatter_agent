from __future__ import annotations

from agent.state import AgentState
from schemas.agent_schema import AgentOutput, AgentTraceItem


def build_output(state: AgentState) -> AgentOutput:
    # 将最终 AgentState 组织成对外可读的结构化输出。
    return AgentOutput(
        result=state.result,
        warnings=state.warnings,
        stop_reason=state.stop_reason,
        trace=[
            AgentTraceItem(
                round_idx=trace.round_idx,
                action_type=trace.action_type,
                params=trace.params,
                reason=trace.reason,
                summary=trace.summary,
            )
            for trace in state.trace
        ],
        evidence_count=len(state.evidence),
        slots=dict(state.slots),
        metadata=dict(state.metadata),
    )
