"""Turns an incoming event payload into a LifecycleEvent."""

import re
from collections.abc import Mapping
from typing import Any

from orchestrator.errors import ValidationError
from orchestrator.models import Action, LifecycleEvent

_REQUIRED = ("request_id", "type", "resource_id")
# The request id becomes the workflow id and the name of the result file.
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]+")


def parse_event(payload: Mapping[str, Any]) -> LifecycleEvent:
    """Parse e.g. ``{"type": "db.postgres.provision", ...}``. Raises ValidationError."""
    for name in _REQUIRED:
        if not payload.get(name):
            raise ValidationError(f"event is missing {name!r}")
    if not _REQUEST_ID.fullmatch(str(payload["request_id"])):
        raise ValidationError("request_id may only contain letters, digits, '.', '_' and '-'")

    # The last segment is the action; everything before it names the platform.
    resource_type, _, action = str(payload["type"]).rpartition(".")
    if not resource_type:
        raise ValidationError(
            f"event type {payload['type']!r} must look like <resource type>.<action>"
        )
    try:
        parsed_action = Action(action)
    except ValueError:
        known = ", ".join(a.value for a in Action)
        raise ValidationError(f"unknown action {action!r}; expected one of: {known}") from None

    return LifecycleEvent(
        request_id=str(payload["request_id"]),
        resource_type=resource_type,
        action=parsed_action,
        resource_id=str(payload["resource_id"]),
        params=dict(payload.get("params") or {}),
    )
