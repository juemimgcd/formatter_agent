from schemas.search_schema import StructuredResultItem
from utils.intent_parser import parse_search_intent
from utils.planner import build_execution_plan
from utils.schema_registry import resolve_output_schema
from utils.task_service_helpers import evaluate_result_quality


def _structured_item(*, quality_score: int = 80, url: str = "https://example.com"):
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


def test_planner_steps_describe_existing_pipeline():
    intent = parse_search_intent("Python 学习资源清单")
    output_schema = resolve_output_schema(intent)
    plan = build_execution_plan(intent, output_schema)

    assert plan.intent_type == "collection"
    assert plan.schema_name == "generic_search_result"
    assert [step.name for step in plan.steps] == [
        "search",
        "rank",
        "structure",
        "export",
    ]
    assert [step.tool_name for step in plan.steps] == [
        "web_search",
        "candidate_rank",
        "result_structure",
        "excel_export",
    ]


def test_evaluate_result_quality_marks_high_fallback_and_low_results():
    high = evaluate_result_quality([_structured_item()], used_fallback=False)
    fallback = evaluate_result_quality([_structured_item()], used_fallback=True)
    low = evaluate_result_quality([_structured_item(quality_score=20)], used_fallback=False)
    empty = evaluate_result_quality([], used_fallback=False)

    assert high.result_quality == "high"
    assert fallback.result_quality == "fallback"
    assert low.result_quality == "low"
    assert empty.result_quality == "low"
    assert empty.warnings == ["structured result is empty"]
