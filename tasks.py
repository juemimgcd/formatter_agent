from __future__ import annotations

from conf.celery_app import celery_app
from utils.task_runner import execute_task_from_payload


@celery_app.task(name="tasks.run_search_task")
def run_search_task(
    task_id: str,
    request_payload: dict,
    dispatch_payload: dict | None = None,
) -> None:
    execute_task_from_payload(task_id, request_payload, dispatch_payload)
