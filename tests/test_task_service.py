from typing import cast
from unittest.mock import AsyncMock

import pytest

from schemas import SearchRequest, SearchResult, TaskStatus
from utils import task_service


def search_result_item(
    *,
    title: str,
    url: str,
    snippet: str = "搜索摘要",
    source: str = "example.com",
    rank: int = 1,
) -> SearchResult:
    # 构造任务服务测试使用的搜索结果对象。
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet,
        source=source,
        rank=rank,
    )


@pytest.mark.asyncio
async def test_create_pending_task_trims_query_before_persist(monkeypatch):
    db = AsyncMock()
    captured_payload: dict | None = None

    async def fake_create_task_record(db_session, payload):
        nonlocal captured_payload
        captured_payload = payload
        return None

    monkeypatch.setattr(task_service, "create_task_record", fake_create_task_record)

    result = await task_service.create_pending_task(
        SearchRequest(query="  AI 产品经理  ", max_results=5),
        db,
    )

    assert captured_payload is not None
    assert captured_payload["query"] == "AI 产品经理"
    assert result.query == "AI 产品经理"


@pytest.mark.asyncio
async def test_run_search_task_marks_task_failed_when_running_update_raises(
    monkeypatch,
):
    db = AsyncMock()

    statuses: list[str] = []

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        statuses.append(status)
        if status == "running":
            raise RuntimeError("db commit failed")
        return None

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )

    result = await task_service.run_search_task(
        task_id="task-001",
        request=SearchRequest(query="AI 产品经理", max_results=5),
        db=db,
    )

    assert statuses[0] == "running"
    assert statuses[-1] == TaskStatus.FAILED
    assert db.rollback.await_count == 0
    assert result.status == "failed"
    assert result.error is not None
    assert "db commit failed" in cast(str, result.error)


@pytest.mark.asyncio
async def test_run_search_task_returns_timeout_message_when_search_fails(monkeypatch):
    db = AsyncMock()

    recorded_statuses: list[str] = []
    recorded_extra_data: list[dict | None] = []

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        recorded_statuses.append(status)
        recorded_extra_data.append(extra_data)
        return None

    async def fake_search_web(query, *, max_results):
        raise TimeoutError()

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(
        "tools.tool_runner.settings.search_failure_llm_fallback_enabled",
        False,
    )

    result = await task_service.run_search_task(
        task_id="task-002",
        request=SearchRequest(query="python后端面试题库", max_results=5),
        db=db,
    )

    assert recorded_statuses == [
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    ]
    assert result.status == TaskStatus.FAILED
    assert result.total_items == 0
    assert result.preview_items == []
    assert result.message == "联网搜索超时或上游搜索失败，当前未能获取结果"
    assert result.error == "TimeoutError"
    assert recorded_extra_data[-1] is not None
    assert recorded_extra_data[-1]["error_message"] == "TimeoutError"


@pytest.mark.asyncio
async def test_run_search_task_marks_failed_when_intent_stage_raises(monkeypatch):
    db = AsyncMock()

    recorded_statuses: list[TaskStatus] = []

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        recorded_statuses.append(status)
        return None

    def fake_parse_search_intent(query):
        raise RuntimeError("intent parse failed")

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "parse_search_intent", fake_parse_search_intent)

    result = await task_service.run_search_task(
        task_id="task-intent-error-001",
        request=SearchRequest(query="AI 产品经理", max_results=5),
        db=db,
    )

    assert recorded_statuses == [
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    ]
    assert result.status == TaskStatus.FAILED
    assert result.error is not None
    assert "intent parse failed" in result.error


@pytest.mark.asyncio
async def test_run_search_task_uses_fallback_when_structured_stage_times_out(
    monkeypatch,
):
    db = AsyncMock()
    status_updates: list[tuple[TaskStatus, dict | None]] = []

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        status_updates.append((status, extra_data))
        return None

    async def fake_search_web(query, *, max_results):
        return [
            search_result_item(
                title="AI 产品经理搜索结果",
                url="https://example.com/item",
                snippet="这是 AI 产品经理搜索摘要，用于降级路径验证。",
                rank=1,
            )
        ]

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        raise TimeoutError("structured stage timeout")

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(
        task_service, "build_structured_results", fake_build_structured_results
    )
    monkeypatch.setattr(task_service, "export_results_to_excel", lambda items: None)

    result = await task_service.run_search_task(
        task_id="task-003",
        request=SearchRequest(query="AI 产品经理", max_results=5),
        db=db,
    )

    final_update = status_updates[-1][1]

    assert result.status == TaskStatus.PARTIAL_SUCCESS
    assert result.total_items == 1
    assert result.preview_items[0].title == "AI 产品经理搜索结果"
    assert result.result_items[0].title == "AI 产品经理搜索结果"
    final_update = status_updates[-1][1]
    assert final_update is not None
    assert final_update["result_payload"][0]["title"] == "AI 产品经理搜索结果"


@pytest.mark.asyncio
async def test_run_search_task_uses_select_top_candidates_with_fixed_top_k_of_five(
    monkeypatch,
):
    db = AsyncMock()

    captured_top_k: list[int] = []

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        return None

    async def fake_search_web(query, *, max_results):
        return [
            search_result_item(
                title=f"AI 产品经理搜索结果{index}",
                url=f"https://example.com/item-{index}",
                snippet="这是 AI 产品经理搜索摘要，用于验证固定 top_k 行为。",
                rank=index + 1,
            )
            for index in range(6)
        ]

    def fake_select_top_candidates(query, items, *, top_k):
        captured_top_k.append(top_k)
        return items[:top_k]

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        return []

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(task_service, "select_top_candidates", fake_select_top_candidates)
    monkeypatch.setattr(
        task_service, "build_structured_results", fake_build_structured_results
    )

    result = await task_service.run_search_task(
        task_id="task-004",
        request=SearchRequest(query="AI 产品经理", max_results=10),
        db=db,
    )

    assert captured_top_k == [5]
    assert result.status == TaskStatus.PARTIAL_SUCCESS
    assert result.total_items == 5
    assert result.message == "任务执行完成"


@pytest.mark.asyncio
async def test_run_search_task_skips_structured_stage_when_no_top_results(
    monkeypatch,
):
    db = AsyncMock()

    structured_called = False

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        return None

    async def fake_search_web(query, *, max_results):
        return []

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        nonlocal structured_called
        structured_called = True
        return []

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(
        task_service, "build_structured_results", fake_build_structured_results
    )

    result = await task_service.run_search_task(
        task_id="task-005",
        request=SearchRequest(query="AI 产品经理", max_results=5),
        db=db,
    )

    assert structured_called is False
    assert result.status == TaskStatus.SUCCESS
    assert result.total_items == 0


@pytest.mark.asyncio
async def test_run_search_task_falls_back_when_structured_results_are_empty(
    monkeypatch,
):
    db = AsyncMock()

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        return None

    async def fake_search_web(query, *, max_results):
        return [
            search_result_item(
                title="宋词大全",
                url="https://example.com/songci",
                snippet="收录大量宋词内容。",
                rank=1,
            )
        ]

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        return []

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(
        task_service, "build_structured_results", fake_build_structured_results
    )
    monkeypatch.setattr(task_service, "export_results_to_excel", lambda items: None)

    result = await task_service.run_search_task(
        task_id="task-005-empty-structured",
        request=SearchRequest(query="宋词大全", max_results=5),
        db=db,
    )

    assert result.status == TaskStatus.PARTIAL_SUCCESS
    assert result.total_items == 1
    assert result.result_items[0].title == "宋词大全"


@pytest.mark.asyncio
async def test_run_search_task_keeps_structured_results_order_and_duplicates(
    monkeypatch,
):
    db = AsyncMock()

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        return None

    async def fake_search_web(query, *, max_results):
        return [
            search_result_item(
                title="AI 产品经理搜索结果1",
                url="https://example.com/item-1",
                snippet="AI 产品经理搜索摘要1",
                rank=1,
            ),
            search_result_item(
                title="AI 产品经理搜索结果2",
                url="https://example.com/item-2",
                snippet="AI 产品经理搜索摘要2",
                rank=2,
            ),
        ]

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        return [
            task_service.StructuredResultItem(
                query=query,
                title="重复结果",
                source="web",
                url="https://example.com/item-1",
                summary="第一条重复结果",
                quality_score=80,
            ),
            task_service.StructuredResultItem(
                query=query,
                title="重复结果",
                source="web",
                url="https://example.com/item-1",
                summary="第二条重复结果",
                quality_score=65,
            ),
        ]

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(
        task_service, "build_structured_results", fake_build_structured_results
    )
    monkeypatch.setattr(task_service, "export_results_to_excel", lambda items: None)

    result = await task_service.run_search_task(
        task_id="task-006",
        request=SearchRequest(query="AI 产品经理", max_results=10),
        db=db,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.total_items == 2
    assert [item.summary for item in result.result_items] == [
        "第一条重复结果",
        "第二条重复结果",
    ]


@pytest.mark.asyncio
async def test_run_search_task_marks_degraded_success_when_search_has_warning(
    monkeypatch,
):
    db = AsyncMock()

    async def fake_update_task_record_status(
        db_session, task_id, status, extra_data=None
    ):
        return None

    async def fake_search_web(query, *, max_results):
        return [
            search_result_item(
                title="AI 产品经理搜索结果",
                url="https://example.com/item-1",
                snippet="AI 产品经理搜索摘要",
                rank=1,
            ).model_copy(update={"notes": ["enrich_failed=TimeoutError"]})
        ]

    async def fake_build_structured_results(
        *, query, rebuilt_prompt_input_text, max_output_items
    ):
        return [
            task_service.StructuredResultItem(
                query=query,
                title="AI 产品经理搜索结果",
                source="web",
                url="https://example.com/item-1",
                summary="结构化结果",
                quality_score=80,
            )
        ]

    monkeypatch.setattr(
        task_service, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_service, "search_web", fake_search_web)
    monkeypatch.setattr(
        task_service,
        "build_structured_results",
        fake_build_structured_results,
    )
    monkeypatch.setattr(task_service, "export_results_to_excel", lambda items: None)

    result = await task_service.run_search_task(
        task_id="task-degraded",
        request=SearchRequest(query="AI 产品经理", max_results=5),
        db=db,
    )

    assert result.status == TaskStatus.DEGRADED_SUCCESS
    assert result.result_quality == "high"
    assert result.warnings == ["enrich_failed=TimeoutError"]
