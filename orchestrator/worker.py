"""Runs the worker: `python -m orchestrator.worker`."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from orchestrator.activities import ALL_ACTIVITIES
from orchestrator.config import TASK_QUEUE, TEMPORAL_ADDRESS
from orchestrator.workflow import LifecycleWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = await Client.connect(TEMPORAL_ADDRESS)
    # Activities are plain blocking functions (Terraform subprocess, database driver),
    # so they run on threads rather than on the event loop.
    with ThreadPoolExecutor(max_workers=8) as executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[LifecycleWorkflow],
            activities=ALL_ACTIVITIES,
            activity_executor=executor,
        )
        logging.info("worker listening on task queue %r at %s", TASK_QUEUE, TEMPORAL_ADDRESS)
        await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
