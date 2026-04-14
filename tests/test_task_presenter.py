from types import SimpleNamespace

from schemas import TaskStatus
from utils.task_presenter import build_task_item_from_record


def test_build_task_item_from_record_uses_empty_success_message():
    record = SimpleNamespace(
        task_id="task-001",
        query="宋词大全",
        status=TaskStatus.SUCCESS,
        result_count=0,
        excel_path=None,
        result_payload=[],
        error_message=None,
    )

    item = build_task_item_from_record(record)

    assert item.status == TaskStatus.SUCCESS
    assert item.total_items == 0
    assert item.message == "未找到可用结果"
