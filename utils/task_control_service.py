def can_retry(status: str) -> bool:
    # 判断当前任务状态是否允许执行重试操作。
    return status in {"failed", "timeout", "partial_success"}
