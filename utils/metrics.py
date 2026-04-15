from collections import defaultdict
from schemas.task_observability_schema import TaskLogContext


def build_task_log_context(
    task_id: str,
    stage: str,
    *,
    attempt_count: int = 0,
    provider: str = "",
    duration_ms: float | None = None,
    error_code: str = "",
) -> TaskLogContext:
    return TaskLogContext(
        task_id=task_id,
        stage=stage,
        attempt_count=attempt_count,
        provider=provider,
        duration_ms=duration_ms,
        error_code=error_code,
    )


def record_stage_latency(
    metrics: defaultdict[str, list[float]],
    stage: str,
    duration_ms: float,
) -> None:
    bucket = metrics.setdefault(stage, [])
    bucket.append(round(duration_ms, 2))