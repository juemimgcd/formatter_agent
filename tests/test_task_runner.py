from types import SimpleNamespace

from schemas import TaskStatus
from utils import task_runner


class FakeSessionContext:
    async def __aenter__(self):
        return "db"

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSessionLocal:
    def begin(self):
        return FakeSessionContext()


def test_execute_task_from_payload_skips_old_message_without_dispatch_payload(
    monkeypatch,
):
    updates: list[dict] = []
    run_called = False

    async def fake_get_task_record_by_task_id(db, task_id):
        return SimpleNamespace(status=TaskStatus.QUEUED)

    async def fake_update_task_record_status(db, task_id, status, extra_data=None):
        updates.append(
            {
                "task_id": task_id,
                "status": status,
                "extra_data": extra_data,
            }
        )
        return None

    async def fake_run_search_task(task_id, request, db):
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(task_runner, "AsyncSessionLocal", FakeSessionLocal())
    monkeypatch.setattr(
        task_runner, "get_task_record_by_task_id", fake_get_task_record_by_task_id
    )
    monkeypatch.setattr(
        task_runner, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_runner, "run_search_task", fake_run_search_task)

    task_runner.execute_task_from_payload(
        "task-old",
        {"query": "接口压测", "max_results": 5},
    )

    assert run_called is False
    assert updates[0]["task_id"] == "task-old"
    assert updates[0]["status"] == TaskStatus.TIMEOUT
    assert "旧队列残留" in updates[0]["extra_data"]["error_message"]


def test_execute_task_from_payload_skips_non_runnable_task_status(monkeypatch):
    updates: list[dict] = []
    run_called = False

    async def fake_get_task_record_by_task_id(db, task_id):
        return SimpleNamespace(status=TaskStatus.SUCCESS)

    async def fake_update_task_record_status(db, task_id, status, extra_data=None):
        updates.append({"status": status, "extra_data": extra_data})
        return None

    async def fake_run_search_task(task_id, request, db):
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(task_runner, "AsyncSessionLocal", FakeSessionLocal())
    monkeypatch.setattr(
        task_runner, "get_task_record_by_task_id", fake_get_task_record_by_task_id
    )
    monkeypatch.setattr(
        task_runner, "update_task_record_status", fake_update_task_record_status
    )
    monkeypatch.setattr(task_runner, "run_search_task", fake_run_search_task)

    task_runner.execute_task_from_payload(
        "task-success",
        {"query": "接口压测", "max_results": 5},
    )

    assert run_called is False
    assert updates == []
