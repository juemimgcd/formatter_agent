from pydantic import BaseModel


class TaskLogContext(BaseModel):
    task_id: str
    stage: str
    attempt_count: int = 0
    provider: str = ""
    duration_ms: float | None = None
    error_code: str = ""