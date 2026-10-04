"""Everything the workflow does that touches the outside world.

The activities are platform-agnostic: each resolves the adapter from the event's
resource type. This is also the only module that turns domain errors into Temporal
failures, which is where "retry or stop" is decided.
"""

import dataclasses
import functools
import json
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from temporalio import activity
from temporalio.exceptions import ApplicationError

from orchestrator.config import RESULTS_DIR
from orchestrator.errors import OrchestratorError
from orchestrator.models import Action, LifecycleEvent, LifecycleResult, TerraformOutcome
from orchestrator.platforms.base import PlatformAdapter
from orchestrator.platforms.registry import get_adapter
from orchestrator.terraform.runner import Terraform

P = ParamSpec("P")
R = TypeVar("R")


def translate_errors(fn: Callable[P, R]) -> Callable[P, R]:
    """Re-raise domain errors as Temporal failures, keeping their retryable flag."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except OrchestratorError as error:
            raise ApplicationError(
                str(error), type=type(error).__name__, non_retryable=not error.retryable
            ) from error

    return wrapper


def _open(event: LifecycleEvent) -> tuple[PlatformAdapter, Terraform]:
    adapter = get_adapter(event.resource_type)
    terraform = Terraform(adapter.module_dir, adapter.workspace(event))
    # Cheap once providers are installed, and it makes each activity self-contained:
    # any attempt may be the first to run on this machine.
    terraform.init()
    return adapter, terraform


@activity.defn
@translate_errors
def validate_request(event: LifecycleEvent) -> None:
    adapter, terraform = _open(event)
    adapter.validate(event, terraform.outputs())


@activity.defn
@translate_errors
def run_terraform(event: LifecycleEvent) -> TerraformOutcome:
    """Apply or destroy, by action. Returns only the outputs that are safe to report."""
    adapter, terraform = _open(event)
    tf_vars = adapter.tf_vars(event, terraform.outputs())
    if event.action is Action.DECOMMISSION:
        return TerraformOutcome(changed=terraform.destroy(tf_vars))
    changed = terraform.apply(tf_vars)
    return TerraformOutcome(
        changed=changed, outputs=adapter.public_outputs(terraform.outputs() or {})
    )


@activity.defn
@translate_errors
def verify_resource(event: LifecycleEvent) -> None:
    adapter, terraform = _open(event)
    # Outputs are read here, not passed in by the workflow: they include the database
    # password, which must never be written to workflow history.
    adapter.verify(event, terraform.outputs())


@activity.defn
@translate_errors
def report_result(result: LifecycleResult) -> None:
    """Notify: a log line, plus results/<request_id>.json as the durable record."""
    activity.logger.info(
        "%s %s for %s: %s", result.event_type, result.status, result.resource_id, result.detail
    )
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{result.request_id}.json"
    path.write_text(json.dumps(dataclasses.asdict(result), indent=2) + "\n", encoding="utf-8")


ALL_ACTIVITIES = [validate_request, run_terraform, verify_resource, report_result]
