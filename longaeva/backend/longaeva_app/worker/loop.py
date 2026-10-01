"""Polling worker loop."""

from __future__ import annotations

import logging
import signal
import sys
import time

# Ensure built-in handlers (e.g. ping) are registered.
import longaeva_app.worker.handlers  # noqa: F401
from longaeva_app.config import get_settings
from longaeva_app.db.session import get_session_factory
from longaeva_app.worker.healthcheck import write_heartbeat
from longaeva_app.worker.queue import claim_next_job, execute_job, fail_orphaned_running_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_stop = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _stop
    logger.info("Received signal %s; shutting down after current job", signum)
    _stop = True


def run_forever() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    worker_id = settings.worker_id
    poll_interval = settings.worker_poll_interval_sec
    heartbeat_path = settings.worker_heartbeat_path

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    fail_orphaned_running_jobs(session_factory, worker_id)
    write_heartbeat(heartbeat_path)
    logger.info("Worker %s started; polling every %.2fs", worker_id, poll_interval)

    while not _stop:
        write_heartbeat(heartbeat_path)
        job_id = claim_next_job(session_factory, worker_id)
        if job_id is None:
            time.sleep(poll_interval)
            continue
        logger.info("Claimed job %s", job_id)
        execute_job(session_factory, job_id, worker_id)

    logger.info("Worker %s stopped", worker_id)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
