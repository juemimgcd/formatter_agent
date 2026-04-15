import sys

from celery import Celery

from conf.settings import settings


def build_celery_app() -> Celery:
    app = Celery(
        "rebuild_agent",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["tasks"],
    )
    app.conf.update(
        task_default_queue="search_queue",
        task_routes={
            "tasks.run_search_task": {"queue": "search_queue"},
        },
        task_track_started=True,
        task_time_limit=90,
        task_soft_time_limit=75,
        task_acks_late=True,
    )
    if sys.platform.startswith("win"):
        app.conf.update(
            worker_pool="solo",
            worker_concurrency=1,
        )
    return app


celery_app = build_celery_app()
