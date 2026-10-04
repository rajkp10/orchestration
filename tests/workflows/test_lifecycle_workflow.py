import pytest
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.worker import Worker

from orchestrator.models import Action, Status
from orchestrator.trigger import start
from orchestrator.workflow import LifecycleWorkflow

PIPELINE = ["validate_request", "run_terraform", "verify_resource", "report_result"]


def transient(message: str) -> ApplicationError:
    return ApplicationError(message, type="TerraformTransientError")


def permanent(message: str) -> ApplicationError:
    return ApplicationError(message, type="ValidationError", non_retryable=True)


def worker(env, task_queue, fakes) -> Worker:
    return Worker(
        env.client, task_queue=task_queue, workflows=[LifecycleWorkflow], activities=fakes.all()
    )


async def run(env, task_queue, fakes, event):
    async with worker(env, task_queue, fakes):
        return await env.client.execute_workflow(
            LifecycleWorkflow.run, event, id=event.request_id, task_queue=task_queue
        )


async def run_expecting_failure(env, task_queue, fakes, event) -> ApplicationError:
    with pytest.raises(WorkflowFailureError) as raised:
        await run(env, task_queue, fakes, event)
    assert isinstance(raised.value.cause, ApplicationError)
    return raised.value.cause


@pytest.mark.parametrize("action", list(Action))
async def test_every_action_runs_the_same_pipeline(env, task_queue, fakes, make_event, action):
    event = make_event(action, version="16.3")

    result = await run(env, task_queue, fakes, event)

    assert fakes.calls == PIPELINE
    assert result.status is Status.COMPLETED
    assert result.event_type == f"db.postgres.{action.value}"
    assert result.outputs == ({} if action is Action.DECOMMISSION else fakes.outputs)
    assert result.changed
    assert result.detail == f"{action.value} applied and verified"
    assert fakes.reported == [result]


async def test_request_that_changes_nothing_says_so(env, task_queue, fakes, make_event):
    # E.g. a patch to the version already running, or decommissioning something gone.
    fakes.changed = False

    result = await run(env, task_queue, fakes, make_event(Action.PATCH, version="16.4"))

    assert fakes.calls == PIPELINE
    assert result.status is Status.COMPLETED
    assert not result.changed
    assert result.detail == "patch needed no changes; current state verified"


async def test_verify_failure_without_a_change_does_not_claim_one(
    env, task_queue, fakes, make_event
):
    fakes.changed = False
    fakes.failures["verify_resource"] = [transient("cannot connect")] * 20

    await run_expecting_failure(env, task_queue, fakes, make_event(Action.PATCH, version="16.4"))

    assert fakes.reported[0].status is Status.VERIFICATION_FAILED
    assert fakes.reported[0].detail.startswith("patch needed no changes but verification failed")


async def test_invalid_request_fails_fast_without_touching_infrastructure(
    env, task_queue, fakes, make_event
):
    fakes.failures["validate_request"] = [permanent("patch cannot downgrade (16.4 -> 16.2)")]

    failure = await run_expecting_failure(
        env, task_queue, fakes, make_event(Action.PATCH, version="16.2")
    )

    assert fakes.calls == ["validate_request", "report_result"]
    assert failure.type == "FAILED"
    assert fakes.reported[0].status is Status.FAILED
    assert "validate failed: patch cannot downgrade" in fakes.reported[0].detail


async def test_transient_terraform_failure_is_retried(env, task_queue, fakes, make_event):
    fakes.failures["run_terraform"] = [transient("state lock"), transient("state lock")]

    result = await run(env, task_queue, fakes, make_event(Action.PROVISION, version="16.3"))

    assert fakes.calls.count("run_terraform") == 3
    assert result.status is Status.COMPLETED


async def test_terraform_failure_that_persists_ends_failed_without_verifying(
    env, task_queue, fakes, make_event
):
    fakes.failures["run_terraform"] = [transient("docker daemon unreachable")] * 10

    await run_expecting_failure(
        env, task_queue, fakes, make_event(Action.PROVISION, version="16.3")
    )

    assert fakes.calls.count("run_terraform") == 4
    assert "verify_resource" not in fakes.calls
    assert fakes.reported[0].status is Status.FAILED
    assert "terraform failed: docker daemon unreachable" in fakes.reported[0].detail


async def test_verify_failure_after_apply_is_reported_as_partial_failure(
    env, task_queue, fakes, make_event
):
    fakes.failures["verify_resource"] = [transient("Postgres reports version 16.3")] * 20

    failure = await run_expecting_failure(
        env, task_queue, fakes, make_event(Action.PATCH, version="16.4")
    )

    assert fakes.calls.count("run_terraform") == 1
    assert fakes.calls.count("verify_resource") == 8
    assert failure.type == "VERIFICATION_FAILED"
    reported = fakes.reported[0]
    assert reported.status is Status.VERIFICATION_FAILED
    assert "left in place" in reported.detail
    # What was applied is still reported, so the operator knows what exists.
    assert reported.outputs == fakes.outputs


async def test_verify_that_recovers_within_its_retries_completes(
    env, task_queue, fakes, make_event
):
    fakes.failures["verify_resource"] = [transient("connection refused")] * 3

    result = await run(env, task_queue, fakes, make_event(Action.PROVISION, version="16.3"))

    assert result.status is Status.COMPLETED


async def test_status_query_reports_the_outcome(env, task_queue, fakes, make_event):
    event = make_event(Action.PROVISION, version="16.3")

    async with worker(env, task_queue, fakes):
        handle = await env.client.start_workflow(
            LifecycleWorkflow.run, event, id=event.request_id, task_queue=task_queue
        )
        await handle.result()
        status = await handle.query(LifecycleWorkflow.get_status)

    assert (status.status, status.step) == (Status.COMPLETED, "done")


async def test_same_request_id_never_starts_a_second_workflow(env, task_queue, fakes, make_event):
    event = make_event(Action.PROVISION, version="16.3")

    async with worker(env, task_queue, fakes):
        first = await start(env.client, event, task_queue)
        await first.result()
        # Rejected even though the first run has finished: an id is never reused.
        with pytest.raises(WorkflowAlreadyStartedError):
            await start(env.client, event, task_queue)

    assert fakes.calls == PIPELINE
