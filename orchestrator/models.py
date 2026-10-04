"""Data passed between the trigger, the workflow and its activities.

Plain dataclasses so Temporal's default converter can serialise them. Nothing here may
carry a secret: these values are stored in workflow history.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    PROVISION = "provision"
    PATCH = "patch"
    DECOMMISSION = "decommission"


class Status(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    # Terraform changed the resource but the check afterwards did not pass.
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


@dataclass(frozen=True)
class LifecycleEvent:
    request_id: str
    resource_type: str
    action: Action
    resource_id: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def event_type(self) -> str:
        return f"{self.resource_type}.{self.action.value}"


@dataclass(frozen=True)
class TerraformOutcome:
    # False when the resource was already in the requested state.
    changed: bool
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LifecycleResult:
    request_id: str
    event_type: str
    resource_id: str
    status: Status
    detail: str
    changed: bool = False
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowStatus:
    status: Status
    step: str
    detail: str
