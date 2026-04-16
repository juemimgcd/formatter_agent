from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from schemas.agent_schema import AgentRuntimeResult, StateSchemaPayload


SlotStatus = Literal["missing", "partial", "filled", "conflict"]


@dataclass
class Evidence:
    field: str | None
    value: Any
    source: str
    confidence: float
    note: str = ""


@dataclass
class ActionTrace:
    round_idx: int
    action_type: str
    params: dict[str, Any]
    reason: str
    summary: str = ""


@dataclass
class AgentState:
    query: str
    task_type: str
    schema: StateSchemaPayload
    slots: dict[str, SlotStatus]
    task_id: str = ""
    max_results: int = 5
    result: AgentRuntimeResult = field(default_factory=AgentRuntimeResult)
    evidence: list[Evidence] = field(default_factory=list)
    trace: list[ActionTrace] = field(default_factory=list)
    round_idx: int = 0
    max_rounds: int = 4
    done: bool = False
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def required_slots(state: AgentState) -> list[str]:
    # 从状态 schema 中读取本轮任务必须填满的槽位。
    return list(state.schema.required_slots)


def required_slots_filled(state: AgentState) -> bool:
    # 判断所有必填槽位是否已经进入 filled 状态。
    return all(state.slots.get(slot) == "filled" for slot in required_slots(state))
