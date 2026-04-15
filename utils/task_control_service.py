def can_cancel(status: str) -> bool:
    return status in {"queued", "running", "retrying"}


def can_retry(status: str) -> bool:
    return status in {"failed", "timeout", "partial_success"}