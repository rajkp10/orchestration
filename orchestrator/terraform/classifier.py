"""Decides whether a failed Terraform command is worth retrying."""

import re

from orchestrator.errors import (
    OrchestratorError,
    TerraformPermanentError,
    TerraformTransientError,
)

# Failures that waiting cannot fix: the configuration or the request is wrong, or
# something outside Terraform's state already holds the name. A person has to act.
_PERMANENT = re.compile(
    r"Invalid value for variable"
    r"|Unsupported argument"
    r"|Unsupported block type"
    r"|Missing required argument"
    r"|No value for required variable"
    r"|is already in use"
    r"|manifest (for \S+ not found|unknown)",
    re.IGNORECASE,
)

_FIRST_ERROR = re.compile(r"^Error: (.+)$", re.MULTILINE)


def classify(command: str, stderr: str) -> OrchestratorError:
    """Build the error for a failed ``terraform <command>`` from its stderr.

    Anything not recognised as permanent is treated as transient. Apply and destroy
    converge on the same end state however often they run, so a retry is safe, and the
    activity's retry policy caps the attempts. State locks and Docker daemon or
    registry blips, the common cases, clear on their own.
    """
    first_error = _FIRST_ERROR.search(stderr)
    reason = first_error[1].strip() if first_error else stderr.strip()[-300:]
    message = f"terraform {command} failed: {reason}"
    if _PERMANENT.search(stderr):
        return TerraformPermanentError(message)
    return TerraformTransientError(message)
