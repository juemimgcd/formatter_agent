from starlette.background import BackgroundTasks

from utils.response import success_response


def test_success_response_preserves_background_tasks():
    background_tasks = BackgroundTasks()

    response = success_response(
        data={"ok": True},
        status_code=202,
        background=background_tasks,
    )

    assert response.background is background_tasks
    assert response.status_code == 202
