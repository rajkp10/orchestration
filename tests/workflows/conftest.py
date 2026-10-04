"""Shared setup for workflow tests.

The real LifecycleWorkflow runs on a real Worker against Temporal's time-skipping test
server, so retry back-offs take no wall-clock time.
"""

import uuid
from typing import Any

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from orchestrator.models import Action, LifecycleEvent, LifecycleResult, TerraformOutcome


class FakeActivities:
    """Stand-ins registered under the real activity names.

    Each records its calls and raises whatever is queued for it in ``failures``.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reported: list[LifecycleResult] = []
        self.failures: dict[str, list[ApplicationError]] = {}
        self.outputs: dict[str, Any] = {"endpoint": "fake:1"}
        self.changed = True

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        queued = self.failures.get(name)
        if queued:
            raise queued.pop(0)

    @activity.defn(name="validate_request")
    async def validate_request(self, event: LifecycleEvent) -> None:
        self._enter("validate_request")

    @activity.defn(name="run_terraform")
    async def run_terraform(self, event: LifecycleEvent) -> TerraformOutcome:
        self._enter("run_terraform")
        outputs = {} if event.action is Action.DECOMMISSION else self.outputs
        return TerraformOutcome(changed=self.changed, outputs=outputs)

    @activity.defn(name="verify_resource")
    async def verify_resource(self, event: LifecycleEvent) -> None:
        self._enter("verify_resource")

    @activity.defn(name="report_result")
    async def report_result(self, result: LifecycleResult) -> None:
        self._enter("report_result")
        self.reported.append(result)

    def all(self) -> list[Any]:
        return [self.validate_request, self.run_terraform, self.verify_resource, self.report_result]


@pytest_asyncio.fixture(scope="session")
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


@pytest.fixture
def fakes() -> FakeActivities:
    return FakeActivities()


@pytest.fixture
def task_queue() -> str:
    return f"test-{uuid.uuid4()}"


@pytest.fixture
def make_event():
    def make(action: Action, resource_type: str = "db.postgres", **params: Any) -> LifecycleEvent:
        return LifecycleEvent(
            request_id=f"req-{uuid.uuid4()}",
            resource_type=resource_type,
            action=action,
            resource_id="orders",
            params=params,
        )

    return make
