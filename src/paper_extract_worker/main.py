"""ARQ worker entrypoint."""

from __future__ import annotations

from arq.connections import RedisSettings

from paper_extract_api.config import settings
from paper_extract_worker.tasks import process_job, worker_startup


class WorkerSettings:
    functions = [process_job]
    on_startup = worker_startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.arq_queue_name
    max_jobs = 1
    job_timeout = 3600
    keep_result = 3600


def run() -> None:
    import logging

    from arq import run_worker

    logging.basicConfig(level=logging.INFO)
    run_worker(WorkerSettings)


if __name__ == "__main__":
    run()
