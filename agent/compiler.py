from __future__ import annotations

from agent.state import AgentState
from schemas.agent_schema import OutputSchema, StateSchemaPayload
from schemas.registry import resolve_output_schema
from utils.intent_parser import parse_search_intent
from utils.task_service_helpers import clean_text


def build_state_schema_payload(output_schema: OutputSchema) -> StateSchemaPayload:
    # 将 Pydantic 输出 schema 转换成 AgentState 中可序列化的 schema 载荷。
    return StateSchemaPayload(
        name=output_schema.name,
        version=output_schema.version,
        description=output_schema.description,
        fields=output_schema.fields,
        output_required_fields=output_schema.required_fields,
        required_slots=["candidates", "structured_results"],
    )


def compile_task(
    query: str,
    *,
    task_id: str = "",
    max_results: int = 5,
    max_rounds: int = 4,
    parse_intent=parse_search_intent,
    resolve_schema=resolve_output_schema,
) -> AgentState:
    # 编译用户 query，生成 Agent Loop 的初始状态对象。
    normalized_query = clean_text(query)
    intent = parse_intent(normalized_query)
    output_schema = resolve_schema(intent)

    return AgentState(
        task_id=task_id,
        query=intent.query,
        task_type=intent.intent_type,
        schema=build_state_schema_payload(output_schema),
        slots={
            "candidates": "missing",
            "structured_results": "missing",
        },
        max_results=max_results,
        max_rounds=max_rounds,
        metadata={
            "intent_reason": intent.reason,
            "schema_name": output_schema.name,
        },
    )
