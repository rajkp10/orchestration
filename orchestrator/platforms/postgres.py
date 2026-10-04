"""PostgreSQL: a real Postgres container created by the Docker Terraform provider."""

import re
import subprocess
from pathlib import Path
from typing import Any

import psycopg

from orchestrator.errors import ValidationError, VerificationError
from orchestrator.models import Action, LifecycleEvent
from orchestrator.platforms.base import Outputs

_MODULE_DIR = Path(__file__).resolve().parents[2] / "terraform" / "modules" / "postgres"
_RESOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_VERSION = re.compile(r"(\d+)\.(\d+)")


def _parse_version(value: object) -> tuple[int, int]:
    match = _VERSION.fullmatch(str(value)) if value is not None else None
    if match is None:
        raise ValidationError(
            f"params.version must look like MAJOR.MINOR (e.g. 16.3), got {value!r}"
        )
    return int(match[1]), int(match[2])


class PostgresAdapter:
    resource_type = "db.postgres"
    module_dir = _MODULE_DIR

    def workspace(self, event: LifecycleEvent) -> str:
        return f"pg-{event.resource_id}"

    def validate(self, event: LifecycleEvent, current: Outputs | None) -> None:
        if not _RESOURCE_ID.fullmatch(event.resource_id):
            raise ValidationError(
                "resource_id must be 1-40 characters of lowercase letters, digits and hyphens"
            )
        if event.action is Action.DECOMMISSION:
            # Valid even if the resource is already gone, so a repeated decommission
            # event ends in the same place instead of failing.
            return

        requested = _parse_version(event.params.get("version"))
        # No recorded version means no working instance, including one whose first
        # apply failed part-way.
        recorded = (current or {}).get("postgres_version")
        if event.action is Action.PROVISION:
            # The same version again is allowed: it lets a half-finished provision converge.
            if recorded is not None and _parse_version(recorded) != requested:
                raise ValidationError(
                    f"{event.resource_id} already exists at version {recorded}; "
                    "send a patch event to change it"
                )
            return

        if recorded is None:
            raise ValidationError(f"{event.resource_id} does not exist, so it cannot be patched")
        running = _parse_version(recorded)
        change = f"{recorded} -> {event.params['version']}"
        if requested[0] != running[0]:
            # A major upgrade on the same data volume needs pg_upgrade, not a new image.
            raise ValidationError(f"patch cannot change the major version ({change})")
        if requested < running:
            raise ValidationError(f"patch cannot downgrade ({change})")

    def tf_vars(self, event: LifecycleEvent, current: Outputs | None) -> dict[str, str]:
        recorded: Outputs = current or {}
        # Provision and patch always carry a version (validate enforces it). Destroy
        # ignores the value, but Terraform still requires every variable to be set.
        version = event.params.get("version", recorded.get("postgres_version", "0.0"))
        tf_vars = {
            "resource_id": event.resource_id,
            "postgres_version": str(version),
            "env": str(event.params.get("env", recorded.get("env", "dev"))),
        }
        if "host_port" in recorded:
            # A patch replaces the container. Pinning the port Docker first chose keeps
            # the instance's address the same for its clients.
            tf_vars["host_port"] = str(recorded["host_port"])
        return tf_vars

    def verify(self, event: LifecycleEvent, outputs: Outputs | None) -> None:
        if event.params.get("simulate_verify_failure"):
            # Fault injection for demonstrating a partial failure: the change has been
            # applied for real, and this check always fails.
            raise VerificationError("simulated verification failure (simulate_verify_failure)")

        if event.action is Action.DECOMMISSION:
            self._verify_gone(event)
        elif outputs is None:
            raise VerificationError(f"{event.resource_id} has no Terraform outputs after apply")
        else:
            self._verify_running(str(event.params["version"]), outputs)

    def public_outputs(self, outputs: Outputs) -> dict[str, Any]:
        return {name: value for name, value in outputs.items() if name != "password"}

    def _verify_gone(self, event: LifecycleEvent) -> None:
        # Asks Docker rather than Terraform, so the check is independent of the tool
        # that made the change.
        name = self.workspace(event)
        found = subprocess.run(["docker", "inspect", name], capture_output=True, check=False)
        if found.returncode == 0:
            raise VerificationError(f"container {name} still exists after destroy")

    def _verify_running(self, expected_version: str, outputs: Outputs) -> None:
        try:
            with psycopg.connect(
                host="127.0.0.1",
                port=outputs["host_port"],
                user="postgres",
                password=outputs["password"],
                dbname="postgres",
                connect_timeout=5,
            ) as connection:
                row = connection.execute("SHOW server_version").fetchone()
        except psycopg.OperationalError as error:
            raise VerificationError(f"cannot connect to Postgres: {error}".strip()) from error

        # server_version looks like "16.3 (Debian 16.3-1.pgdg120+1)".
        actual = row[0].split()[0] if row else ""
        if actual != expected_version:
            raise VerificationError(
                f"Postgres reports version {actual}, expected {expected_version}"
            )
