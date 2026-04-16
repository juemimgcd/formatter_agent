import json

import pytest

from agent.compiler import compile_task
from agent.policy import decide_next_action
from agent.runner import run_agent
from schemas.search_schema import StructuredResultItem
from schemas.search_schema import SearchResult
from utils.intent_parser import parse_search_intent
from utils.task_service_helpers import evaluate_result_quality


def structured_item(*, quality_score: int = 80, url: str = "https://example.com"):
    # 构造结构化结果测试对象，便于复用质量分和 URL 断言。
    return StructuredResultItem(
        query="测试 query",
        title="测试结果",
        source="example.com",
        url=url,
        summary="测试摘要",
        quality_score=quality_score,
    )


def test_parse_search_intent_uses_query_shape_not_domain_terms():
    assert parse_search_intent("FastAPI 和 Django 对比").intent_type == "comparison"
    assert parse_search_intent("Python 学习资源清单").intent_type == "collection"
    assert parse_search_intent("LangChain 是什么").intent_type == "lookup"
    assert parse_search_intent("AI 产品经理").intent_type == "general"


def test_task_compiler_initializes_agent_state_slots():
    state = compile_task("Python 学习资源清单", task_id="task-001", max_results=3)

    assert state.task_id == "task-001"
    assert state.task_type == "collection"
    assert state.schema.name == "generic_search_result"
    assert state.schema.required_slots == ["candidates", "structured_results"]
    assert state.slots == {
        "candidates": "missing",
        "structured_results": "missing",
    }


def test_policy_decides_from_state_instead_of_static_pipeline():
    state = compile_task("AI 产品经理", task_id="task-policy")

    assert decide_next_action(state).type == "search"

    state.slots["candidates"] = "filled"
    action = decide_next_action(state)
    assert action.type == "targeted_search"
    assert action.field == "structured_results"

    state.slots["structured_results"] = "filled"
    assert decide_next_action(state).type == "finalize"


def test_evaluate_result_quality_marks_high_fallback_and_low_results():
    high = evaluate_result_quality([structured_item()], used_fallback=False)
    fallback = evaluate_result_quality([structured_item()], used_fallback=True)
    low = evaluate_result_quality([structured_item(quality_score=20)], used_fallback=False)
    empty = evaluate_result_quality([], used_fallback=False)

    assert high.result_quality == "high"
    assert fallback.result_quality == "fallback"
    assert low.result_quality == "low"
    assert empty.result_quality == "low"
    assert empty.warnings == ["structured result is empty"]


@pytest.mark.asyncio
async def test_run_agent_returns_trace_slots_and_final_result():
    async def fake_search_web(query, *, max_results):
        return [
            SearchResult(
                title="AI 产品经理示例结果",
                url="https://example.com/agent",
                snippet="AI 产品经理 Agent loop 测试摘要",
                source="example.com",
                rank=1,
            )
        ]

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        return [
            StructuredResultItem(
                query=query,
                title="结构化结果",
                source="example.com",
                url="https://example.com/agent",
                summary="由 fake LLM 生成的结构化结果",
                quality_score=88,
            )
        ]

    output = await run_agent(
        "AI 产品经理",
        task_id="task-agent",
        max_results=5,
        search_func=fake_search_web,
        build_structured_results_func=fake_build_structured_results,
        export_results_to_excel_func=lambda items: "result.xlsx",
    )

    assert output.stop_reason == "required_slots_filled"
    assert output.slots == {
        "candidates": "filled",
        "structured_results": "filled",
    }
    assert [trace.action_type for trace in output.trace] == [
        "search",
        "targeted_search",
        "finalize",
    ]
    assert output.result.items[0].title == "结构化结果"
    assert output.result.excel_path == "result.xlsx"
    assert output.evidence_count >= 2


@pytest.mark.asyncio
async def test_run_agent_uses_llm_fallback_candidate_when_search_fails(monkeypatch):
    async def fake_search_web(query, *, max_results):
        raise ConnectionError("network unavailable")

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        payload = json.loads(rebuilt_prompt_input_text)
        fallback_candidate = payload["top_candidates"][0]
        assert fallback_candidate["source"] == "llm_local_knowledge"
        assert fallback_candidate["url"].startswith("llm://local-knowledge/")
        return [
            StructuredResultItem(
                query=query,
                title="张艺谋作品清单",
                source="llm_local_knowledge",
                url=fallback_candidate["url"],
                summary="基于模型已有知识整理张艺谋导演作品。",
                quality_score=70,
                extraction_notes="local_knowledge_fallback",
            )
        ]

    monkeypatch.setattr(
        "tools.tool_runner.settings.search_failure_llm_fallback_enabled",
        True,
    )

    output = await run_agent(
        "张艺谋作品大全",
        task_id="task-search-fallback",
        max_results=5,
        search_func=fake_search_web,
        build_structured_results_func=fake_build_structured_results,
        export_results_to_excel_func=lambda items: None,
    )

    assert output.stop_reason == "required_slots_filled"
    assert output.result.items[0].source == "llm_local_knowledge"
    assert "web search failed; using llm local knowledge fallback" in output.warnings
    assert [trace.action_type for trace in output.trace] == [
        "search",
        "targeted_search",
        "finalize",
    ]
