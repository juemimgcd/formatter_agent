import importlib

from models.task_record import TaskRecord
from schemas import StructuredResultItem, TaskItem, TaskStatus
from schemas.task_dispatch_schema import DispatchPayload, DispatchResult


task_router_module = importlib.import_module("routers.task_router")


def test_root_endpoint_returns_service_metadata(client):
    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["router_status"] == "mounted"


def test_health_endpoint_returns_healthy_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "healthy"}


def test_create_search_task_returns_accepted_pending_task(client, monkeypatch):
    dispatched_calls: list[tuple[str, str]] = []

    async def fake_create_pending_task(request, db):
        assert request.query == "AI 产品经理"
        assert db is None
        return TaskItem(
            task_id="task-001",
            query=request.query,
            status=TaskStatus.CREATED,
            total_items=0,
            preview_items=[],
            result_items=[],
            message="任务已创建",
        )

    async def fake_dispatch_task(task_id, request):
        dispatched_calls.append((task_id, request.query))
        return DispatchResult(
            accepted=True,
            task_id=task_id,
            dispatch_mode="celery",
            request_payload=DispatchPayload(
                task_id=task_id,
                query=request.query,
                max_results=request.max_results,
                submitted_at="2026-04-15T00:00:00+00:00",
                dispatch_version="v1",
            ),
            queue="search_queue",
            celery_task_id="celery-001",
        )

    monkeypatch.setattr(
        task_router_module, "create_pending_task", fake_create_pending_task
    )
    monkeypatch.setattr(task_router_module, "dispatch_task", fake_dispatch_task)

    response = client.post(
        "/api/v1/tasks/search",
        json={"query": "AI 产品经理", "max_results": 5},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["task_id"] == "task-001"
    assert payload["data"]["status"] == "queued"
    assert payload["data"]["preview_items"] == []
    assert payload["data"]["result_items"] == []
    assert payload["data"]["message"] == "任务已排队"

    assert dispatched_calls == [("task-001", "AI 产品经理")]


def test_create_search_task_returns_http_400_when_task_creation_returns_empty(
    client, monkeypatch
):
    async def fake_create_pending_task(request, db):
        return None

    monkeypatch.setattr(
        task_router_module, "create_pending_task", fake_create_pending_task
    )

    response = client.post(
        "/api/v1/tasks/search",
        json={"query": "AI 产品经理", "max_results": 5},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "任务创建失败"


def test_create_search_task_validation_errors_are_wrapped(client):
    response = client.post(
        "/api/v1/tasks/search",
        json={"query": "", "max_results": 0},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"] == "请求参数校验失败"
    assert len(payload["data"]) >= 1


def test_get_task_detail_returns_wrapped_task_with_result_items(client, monkeypatch):
    async def fake_get_task_record_by_task_id(db, task_id):
        assert db is None
        assert task_id == "task-001"
        item = StructuredResultItem(
            query="AI 产品经理",
            title="示例结果",
            source="docs",
            url="https://example.com",
            summary="结构化摘要足够长，用来保证模型评分与预览逻辑稳定。",
            quality_score=88,
        )
        return TaskRecord(
            task_id=task_id,
            query="AI 产品经理",
            status=TaskStatus.SUCCESS.value,
            result_count=1,
            excel_path=None,
            result_payload=[item.model_dump(mode="json")],
            error_message=None,
        )

    monkeypatch.setattr(
        task_router_module,
        "get_task_record_by_task_id",
        fake_get_task_record_by_task_id,
    )

    response = client.get("/api/v1/tasks/task-001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["task_id"] == "task-001"
    assert payload["data"]["result_items"][0]["title"] == "示例结果"


def test_get_task_detail_returns_404_when_missing(client, monkeypatch):
    async def fake_get_task_record_by_task_id(db, task_id):
        return None

    monkeypatch.setattr(
        task_router_module,
        "get_task_record_by_task_id",
        fake_get_task_record_by_task_id,
    )

    response = client.get("/api/v1/tasks/missing-task")

    assert response.status_code == 404
    assert response.json()["detail"] == "tasks not found"


def test_unexpected_errors_are_wrapped_by_global_handler(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    async def fake_create_pending_task(request, db):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        task_router_module, "create_pending_task", fake_create_pending_task
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/tasks/search",
            json={"query": "AI 产品经理", "max_results": 5},
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "服务内部异常" in payload["message"]
