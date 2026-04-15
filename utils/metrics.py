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
    # 构造任务日志埋点统一使用的上下文对象。
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
    # 把某个阶段的耗时记录到指标桶里供后续统计使用。
    bucket = metrics.setdefault(stage, [])
    bucket.append(round(duration_ms, 2))
