"""The one workflow that runs every lifecycle event, for every platform.

Workflow code must be deterministic, so nothing here does I/O: each step is an activity.
Nothing here names a platform or branches on the action either; the activities resolve
the platform adapter from the event, and the adapter and the action decide what
"validate", "terraform" and "verify" mean.
"""

from datetime import timedelta
from typing import NoReturn

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

# The activities module pulls in subprocess and database code. It is referenced here
# only for type-safe activity names, so it bypasses the workflow sandbox's re-import.
with workflow.unsafe.imports_passed_through():
    from orchestrator import activities
    from orchestrator.models import (
        LifecycleEvent,
        LifecycleResult,
        Status,
        TerraformOutcome,
        WorkflowStatus,
    )

# Reported when a request fails before Terraform has done anything.
_NOTHING = TerraformOutcome(changed=False)

# In every policy below, a failure the activity marked non-retryable (invalid request,
# bad Terraform configuration, name conflict) stops at the first attempt whatever
# maximum_attempts says: no amount of waiting fixes it, so it goes straight to a person.

# Validation only reads state. Retrying is free and covers a state lock held by another
# run or a Docker hiccup.
_VALIDATE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_attempts=4,
)

# Apply and destroy change real infrastructure. Retrying is safe because Terraform
# converges on the declared state rather than repeating actions, but attempts are few
# and spaced out: each failed run may have changed something, and a failure that
# persists should reach a person quickly rather than be hammered.
_TERRAFORM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=4,
)

# A database that has just started may refuse connections for a few seconds, so
# verification retries quickly for about a minute. Past that it is not "still starting":
# the resource exists but is wrong, which is a partial failure for an operator.
_VERIFY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=3),
    backoff_coefficient=1.5,
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=8,
)

# Reporting is cheap and idempotent (it overwrites one file), and losing it would hide
# the outcome, so it is retried generously.
_REPORT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=10,
)


def _reason(error: ActivityError) -> str:
    cause = error.cause
    return cause.message if isinstance(cause, ApplicationError) else str(cause)


@workflow.defn
class LifecycleWorkflow:
    def __init__(self) -> None:
        self._status = Status.RUNNING
        self._step = "starting"
        self._detail = ""

    @workflow.query
    def get_status(self) -> WorkflowStatus:
        return WorkflowStatus(status=self._status, step=self._step, detail=self._detail)

    @workflow.run
    async def run(self, event: LifecycleEvent) -> LifecycleResult:
        self._event = event
        try:
            self._step = "validate"
            await workflow.execute_activity(
                activities.validate_request,
                event,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_VALIDATE_RETRY,
            )
            self._step = "terraform"
            # Generous: a first apply may pull a database image over a slow connection.
            outcome = await workflow.execute_activity(
                activities.run_terraform,
                event,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=_TERRAFORM_RETRY,
            )
        except ActivityError as error:
            detail = f"{self._step} failed: {_reason(error)}"
            if self._step == "terraform":
                # A run that fails part-way can leave some of its changes behind.
                detail += ". The resource may be partly changed."
            await self._fail(Status.FAILED, detail, _NOTHING)

        # A request for a state the resource is already in (a repeated event under a
        # new request id) still succeeds, but must not claim it applied anything.
        action = event.action.value
        did = f"{action} was applied" if outcome.changed else f"{action} needed no changes"

        try:
            self._step = "verify"
            await workflow.execute_activity(
                activities.verify_resource,
                event,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_VERIFY_RETRY,
            )
        except ActivityError as error:
            # Partial failure: Terraform succeeded, the check did not. Nothing is undone
            # automatically, because the resource may hold data and the fault may lie
            # with the check. It is reported under its own status so an operator can
            # tell "nothing happened" from "changed but unverified".
            await self._fail(
                Status.VERIFICATION_FAILED,
                f"{did} but verification failed: {_reason(error)}. "
                "The resource was left in place; resend the event with a new request id "
                "to verify again.",
                outcome,
            )

        if outcome.changed:
            return await self._report(Status.COMPLETED, f"{action} applied and verified", outcome)
        return await self._report(Status.COMPLETED, f"{did}; current state verified", outcome)

    async def _report(
        self, status: Status, detail: str, outcome: TerraformOutcome
    ) -> LifecycleResult:
        self._status = status
        self._detail = detail
        result = LifecycleResult(
            request_id=self._event.request_id,
            event_type=self._event.event_type,
            resource_id=self._event.resource_id,
            status=status,
            detail=detail,
            changed=outcome.changed,
            outputs=outcome.outputs,
        )
        await workflow.execute_activity(
            activities.report_result,
            result,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_REPORT_RETRY,
        )
        self._step = "done"
        return result

    async def _fail(self, status: Status, detail: str, outcome: TerraformOutcome) -> NoReturn:
        """Report the outcome, then fail the execution so Temporal shows it as failed."""
        try:
            await self._report(status, detail, outcome)
        except ActivityError:
            # The original failure is the one worth surfacing, not the reporting failure.
            workflow.logger.exception("could not record the %s result", status.value)
        raise ApplicationError(detail, type=status.value, non_retryable=True)
