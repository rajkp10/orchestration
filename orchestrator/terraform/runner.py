"""Runs the Terraform CLI for one resource.

Each resource has its own Terraform workspace, selected through TF_WORKSPACE, so one
module directory serves every instance and their states never mix.
"""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orchestrator.terraform.classifier import classify

_TIMEOUT_SECONDS = 600
# Exit codes of `terraform plan -detailed-exitcode`; 1 is an error.
_PLAN_NO_CHANGES = 0
_PLAN_HAS_CHANGES = 2


class Terraform:
    def __init__(self, module_dir: Path, workspace: str) -> None:
        self._module_dir = module_dir
        self._workspace = workspace

    def init(self) -> None:
        # With TF_WORKSPACE set, init fails to select a workspace that does not exist
        # yet once any other workspace does. The local backend treats this directory
        # as the workspace, so creating it first avoids that.
        (self._module_dir / "terraform.tfstate.d" / self._workspace).mkdir(
            parents=True, exist_ok=True
        )
        self._run("init", "-input=false")

    def apply(self, tf_vars: Mapping[str, str]) -> bool:
        """Bring the resource to the declared state. Returns whether anything changed."""
        return self._converge("apply", _var_args(tf_vars))

    def destroy(self, tf_vars: Mapping[str, str]) -> bool:
        """Remove the resource. Returns whether there was anything to remove."""
        return self._converge("destroy", _var_args(tf_vars), "-destroy")

    def outputs(self) -> dict[str, Any] | None:
        """The resource's outputs, or None if it does not exist."""
        raw = json.loads(self._run("output", "-json"))
        return {name: entry["value"] for name, entry in raw.items()} or None

    def _converge(self, command: str, var_args: list[str], *plan_flags: str) -> bool:
        # Planning first is how the caller learns whether the request changed anything,
        # so a repeated request can be reported as a no-op rather than as "applied".
        plan = self._execute("plan", "-detailed-exitcode", "-input=false", *plan_flags, *var_args)
        if plan.returncode == _PLAN_NO_CHANGES:
            return False
        if plan.returncode != _PLAN_HAS_CHANGES:
            raise classify("plan", plan.stderr)
        self._run(command, "-auto-approve", "-input=false", *var_args)
        return True

    def _run(self, command: str, *args: str) -> str:
        completed = self._execute(command, *args)
        if completed.returncode != 0:
            raise classify(command, completed.stderr)
        return completed.stdout

    def _execute(self, command: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["terraform", command, *args, "-no-color"],
            cwd=self._module_dir,
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["TF_WORKSPACE"] = self._workspace
        env["TF_IN_AUTOMATION"] = "1"
        if sys.platform == "win32":
            # The Docker provider defaults to the unix socket, which Docker Desktop on
            # Windows does not offer.
            env.setdefault("DOCKER_HOST", "npipe:////./pipe/docker_engine")
        return env


def _var_args(tf_vars: Mapping[str, str]) -> list[str]:
    return [f"-var={name}={value}" for name, value in tf_vars.items()]
