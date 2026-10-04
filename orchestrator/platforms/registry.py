"""Maps an event's resource type to the adapter that handles it.

This is the single place a new platform is plugged in.
"""

from orchestrator.errors import ValidationError
from orchestrator.platforms.base import PlatformAdapter
from orchestrator.platforms.postgres import PostgresAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {}


def register(adapter: PlatformAdapter) -> None:
    _ADAPTERS[adapter.resource_type] = adapter


def get_adapter(resource_type: str) -> PlatformAdapter:
    try:
        return _ADAPTERS[resource_type]
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS))
        raise ValidationError(
            f"no platform handles resource type {resource_type!r}; known: {known}"
        ) from None


register(PostgresAdapter())
