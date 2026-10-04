"""A new platform plugs in with an adapter and a Terraform module, and nothing else.

This runs the unchanged LifecycleWorkflow and the real activities (real Terraform CLI)
for a platform the core has never heard of.
"""

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.worker import Worker

from orchestrator import activities
from orchestrator.errors import ValidationError, VerificationError
from orchestrator.models import Action, Status
from orchestrator.platforms import registry
from orchestrator.workflow import LifecycleWorkflow

FIXTURE_MODULE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_module"

pytestmark = pytest.mark.skipif(shutil.which("terraform") is None, reason="needs terraform")


class FakePlatformAdapter:
    resource_type = "test.fake"

    def __init__(self, module_dir: Path) -> None:
        self.module_dir = module_dir

    def workspace(self, event):
        return f"fake-{event.resource_id}"

    def validate(self, event, current):
        if event.action is Action.PATCH and current is None:
            raise ValidationError(f"{event.resource_id} does not exist")

    def tf_vars(self, event, current):
        recorded = current or {}
        return {
            "resource_id": event.resource_id,
            "release": str(event.params.get("release", recorded.get("release", "none"))),
        }

    def verify(self, event, outputs):
        expected = None if event.action is Action.DECOMMISSION else event.params["release"]
        actual = outputs["release"] if outputs else None
        if actual != expected:
            raise VerificationError(f"release is {actual}, expected {expected}")

    def public_outputs(self, outputs):
        return dict(outputs)


@pytest.fixture
def fake_platform(tmp_path, monkeypatch):
    # A copy, so Terraform's working files and state stay out of the repository.
    module_dir = tmp_path / "module"
    shutil.copytree(FIXTURE_MODULE, module_dir)
    monkeypatch.setitem(registry._ADAPTERS, "test.fake", FakePlatformAdapter(module_dir))
    monkeypatch.setattr(activities, "RESULTS_DIR", tmp_path / "results")
    return tmp_path


async def test_new_platform_runs_the_full_cycle_on_the_unchanged_core(
    env, task_queue, make_event, fake_platform
):
    async def send(action, **params):
        event = make_event(action, resource_type="test.fake", **params)
        return await env.client.execute_workflow(
            LifecycleWorkflow.run, event, id=event.request_id, task_queue=task_queue
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[LifecycleWorkflow],
            activities=activities.ALL_ACTIVITIES,
            activity_executor=executor,
        ):
            provisioned = await send(Action.PROVISION, release="1.0")
            patched = await send(Action.PATCH, release="1.1")
            patched_again = await send(Action.PATCH, release="1.1")
            decommissioned = await send(Action.DECOMMISSION)
            decommissioned_again = await send(Action.DECOMMISSION)
            with pytest.raises(WorkflowFailureError):
                await send(Action.PATCH, release="1.2")

    assert provisioned.status is Status.COMPLETED
    assert provisioned.outputs == {"release": "1.0"}
    assert patched.outputs == {"release": "1.1"}
    assert patched.changed
    assert decommissioned.status is Status.COMPLETED
    assert decommissioned.event_type == "test.fake.decommission"
    # Repeating a request under a new id succeeds, and reports that it did nothing.
    assert (patched_again.status, patched_again.changed) == (Status.COMPLETED, False)
    assert (decommissioned_again.status, decommissioned_again.changed) == (Status.COMPLETED, False)
    assert len(list((fake_platform / "results").glob("*.json"))) == 6
