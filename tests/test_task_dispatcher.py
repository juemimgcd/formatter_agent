import pytest

from schemas import SearchRequest
from utils import task_dispatcher


@pytest.mark.asyncio
async def test_dispatch_search_task_sends_dispatch_payload_and_expiration(monkeypatch):
    captured: dict = {}

    class FakeCeleryResult:
        id = "celery-001"

    def fake_send_task(name, *, kwargs, queue, expires):
        captured["name"] = name
        captured["kwargs"] = kwargs
        captured["queue"] = queue
        captured["expires"] = expires
        return FakeCeleryResult()

    monkeypatch.setattr(task_dispatcher.settings, "celery_task_expires_seconds", 123)
    monkeypatch.setattr(task_dispatcher.celery_app, "send_task", fake_send_task)

    result = await task_dispatcher.dispatch_search_task(
        "task-001",
        SearchRequest(query="接口压测", max_results=5),
    )

    dispatch_payload = captured["kwargs"]["dispatch_payload"]

    assert captured["name"] == "tasks.run_search_task"
    assert captured["queue"] == "search_queue"
    assert captured["expires"] == 123
    assert captured["kwargs"]["request_payload"] == {
        "query": "接口压测",
        "max_results": 5,
    }
    assert dispatch_payload["task_id"] == "task-001"
    assert dispatch_payload["query"] == "接口压测"
    assert dispatch_payload["max_results"] == 5
    assert result.celery_task_id == "celery-001"
