"""The contract a platform implements to be orchestrated.

The workflow and the activities are written against this protocol only. Supporting a
new platform (MongoDB, a Windows or Linux server) means writing one adapter plus its
Terraform module and registering it; the workflow and activities do not change.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from orchestrator.models import LifecycleEvent

# Terraform outputs of a resource, by name. May include secrets, so this type stays
# inside activities and is never returned to the workflow.
Outputs = Mapping[str, Any]


class PlatformAdapter(Protocol):
    @property
    def resource_type(self) -> str:
        """Routing prefix of the events this adapter handles, e.g. ``db.postgres``."""
        ...

    @property
    def module_dir(self) -> Path:
        """Directory of the Terraform module for this platform."""
        ...

    def workspace(self, event: LifecycleEvent) -> str:
        """Terraform workspace holding this resource's state. One per resource."""
        ...

    def validate(self, event: LifecycleEvent, current: Outputs | None) -> None:
        """Reject a request that cannot succeed. Raises ValidationError.

        ``current`` is the resource's present outputs, or None if it does not exist.
        """
        ...

    def tf_vars(self, event: LifecycleEvent, current: Outputs | None) -> dict[str, str]:
        """Terraform input variables for this request."""
        ...

    def verify(self, event: LifecycleEvent, outputs: Outputs | None) -> None:
        """Check the live resource matches the request. Raises VerificationError.

        ``outputs`` is None once the resource has been destroyed.
        """
        ...

    def public_outputs(self, outputs: Outputs) -> dict[str, Any]:
        """The outputs that are safe to report, with secrets left out."""
        ...
