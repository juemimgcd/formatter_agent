def can_cancel(status: str) -> bool:
    # 判断当前任务状态是否允许执行取消操作。
    return status in {"queued", "running", "retrying"}


def can_retry(status: str) -> bool:
    # 判断当前任务状态是否允许执行重试操作。
    return status in {"failed", "timeout", "partial_success"}
