from typing import Literal

from pydantic import BaseModel


class DispatchPayload(BaseModel):
    task_id: str
    query: str
    max_results: int
    submitted_at: str
    dispatch_version: Literal["v1"] = "v1"


class DispatchResult(BaseModel):
    accepted: bool
    task_id: str
    dispatch_mode: str
    request_payload: DispatchPayload
    queue: str = ""
    celery_task_id: str = ""