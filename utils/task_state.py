from schemas.task_schema import TaskStatus


TERMINAL_STATUSES = {
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.TIMEOUT,
    TaskStatus.CANCELLED,
    TaskStatus.EMPTY_RESULT,
}


def is_terminal_status(status: str) -> bool:
    return status in {str(u) for u in TERMINAL_STATUSES}




def can_transition(from_status: str, to_status: str) -> bool:
    allowed = {
        TaskStatus.CREATED: {TaskStatus.QUEUED, TaskStatus.CANCELLED, TaskStatus.FAILED},
        TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.TIMEOUT},
        TaskStatus.RUNNING: {
            TaskStatus.SUCCESS,
            TaskStatus.PARTIAL_SUCCESS,
            TaskStatus.EMPTY_RESULT,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.RETRYING,
            TaskStatus.CANCELLED,
        },
        TaskStatus.RETRYING: {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.TIMEOUT},
    }
    return to_status in {str(item) for item in allowed.get(from_status, set())}















