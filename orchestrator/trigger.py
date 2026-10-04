"""Simulates "an event occurred": `python -m orchestrator.trigger send events/provision.json`."""

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path

from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError

from orchestrator.config import TASK_QUEUE, TEMPORAL_ADDRESS
from orchestrator.errors import ValidationError
from orchestrator.events import parse_event
from orchestrator.models import LifecycleEvent, LifecycleResult
from orchestrator.workflow import LifecycleWorkflow


async def start(
    client: Client, event: LifecycleEvent, task_queue: str = TASK_QUEUE
) -> WorkflowHandle[LifecycleWorkflow, LifecycleResult]:
    """Start the workflow for an event. Raises WorkflowAlreadyStartedError on a duplicate.

    The request id is the workflow id, and an id is never reused, so the same event
    delivered twice starts exactly one workflow, even after the first has finished.
    """
    return await client.start_workflow(
        LifecycleWorkflow.run,
        event,
        id=event.request_id,
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )


async def send(event_file: Path, request_id: str | None) -> int:
    payload = json.loads(event_file.read_text(encoding="utf-8"))
    if request_id:
        payload["request_id"] = request_id
    try:
        event = parse_event(payload)
    except ValidationError as error:
        print(f"invalid event: {error}", file=sys.stderr)
        return 2

    client = await Client.connect(TEMPORAL_ADDRESS)
    try:
        handle = await start(client, event)
    except WorkflowAlreadyStartedError:
        print(
            f"duplicate: request {event.request_id} was already submitted; nothing started. "
            f"See: python -m orchestrator.trigger status {event.request_id}",
            file=sys.stderr,
        )
        return 1

    print(f"started {event.event_type} for {event.resource_id} (request {event.request_id})")
    try:
        result = await handle.result()
    except WorkflowFailureError as error:
        cause = error.cause
        if isinstance(cause, ApplicationError):
            print(f"{cause.type}: {cause.message}", file=sys.stderr)
        else:
            print(f"{type(cause).__name__}: {cause}", file=sys.stderr)
        return 1
    print(json.dumps(dataclasses.asdict(result), indent=2))
    return 0


async def status(request_id: str) -> int:
    client = await Client.connect(TEMPORAL_ADDRESS)
    try:
        current = await client.get_workflow_handle(request_id).query(LifecycleWorkflow.get_status)
    except RPCError as error:
        print(f"cannot get status of {request_id}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(dataclasses.asdict(current), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.trigger")
    commands = parser.add_subparsers(dest="command", required=True)

    send_parser = commands.add_parser("send", help="start a workflow for an event and wait")
    send_parser.add_argument("event_file", type=Path)
    send_parser.add_argument("--request-id", help="override the request id in the file")

    status_parser = commands.add_parser("status", help="show a request's status and step")
    status_parser.add_argument("request_id")

    args = parser.parse_args()
    if args.command == "send":
        return asyncio.run(send(args.event_file, args.request_id))
    return asyncio.run(status(args.request_id))


if __name__ == "__main__":
    sys.exit(main())
