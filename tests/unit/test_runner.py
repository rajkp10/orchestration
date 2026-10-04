import json
import subprocess

import pytest

from orchestrator.errors import TerraformPermanentError
from orchestrator.terraform.runner import Terraform

# `terraform plan -detailed-exitcode` exit codes.
NO_CHANGES, ERROR, CHANGES = 0, 1, 2


class FakeRun:
    """Stands in for subprocess.run: records every call and replays queued results."""

    def __init__(self, *results):
        self.calls = []
        self._results = list(results)

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        returncode, stdout, stderr = self._results.pop(0) if self._results else (0, "", "")
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    def commands(self):
        return [args[1] for args, _ in self.calls]


@pytest.fixture
def module_dir(tmp_path):
    path = tmp_path / "module"
    path.mkdir()
    return path


@pytest.fixture
def fake_run(monkeypatch):
    def install(*results):
        run = FakeRun(*results)
        monkeypatch.setattr(subprocess, "run", run)
        return run

    return install


def _terraform(module_dir):
    return Terraform(module_dir=module_dir, workspace="pg-orders")


def test_apply_plans_first_and_applies_when_there_are_changes(fake_run, module_dir):
    run = fake_run((CHANGES, "", ""))

    changed = _terraform(module_dir).apply({"resource_id": "orders", "postgres_version": "16.3"})

    assert changed
    assert run.commands() == ["plan", "apply"]
    plan_args, apply_args = run.calls[0][0], run.calls[1][0]
    assert "-detailed-exitcode" in plan_args
    assert "-auto-approve" in apply_args
    for args in (plan_args, apply_args):
        assert "-var=resource_id=orders" in args
        assert "-var=postgres_version=16.3" in args


def test_apply_does_nothing_when_the_plan_is_empty(fake_run, module_dir):
    run = fake_run((NO_CHANGES, "", ""))

    changed = _terraform(module_dir).apply({"resource_id": "orders"})

    assert not changed
    assert run.commands() == ["plan"]


def test_destroy_plans_a_destroy_first(fake_run, module_dir):
    run = fake_run((CHANGES, "", ""))

    changed = _terraform(module_dir).destroy({"resource_id": "orders"})

    assert changed
    assert run.commands() == ["plan", "destroy"]
    assert "-destroy" in run.calls[0][0]


def test_destroy_does_nothing_when_nothing_exists(fake_run, module_dir):
    run = fake_run((NO_CHANGES, "", ""))

    assert not _terraform(module_dir).destroy({"resource_id": "orders"})
    assert run.commands() == ["plan"]


def test_every_command_runs_in_the_module_dir_and_resource_workspace(fake_run, module_dir):
    run = fake_run((CHANGES, "", ""))

    _terraform(module_dir).apply({})

    for _, kwargs in run.calls:
        assert kwargs["cwd"] == module_dir
        assert kwargs["env"]["TF_WORKSPACE"] == "pg-orders"


def test_init_creates_the_workspace_directory_first(fake_run, module_dir):
    fake_run()

    _terraform(module_dir).init()

    assert (module_dir / "terraform.tfstate.d" / "pg-orders").is_dir()


def test_outputs_are_flattened_to_plain_values(fake_run, module_dir):
    raw = {
        "host_port": {"sensitive": False, "type": "number", "value": 32768},
        "password": {"sensitive": True, "type": "string", "value": "s3cret"},
    }
    fake_run((0, json.dumps(raw), ""))

    assert _terraform(module_dir).outputs() == {"host_port": 32768, "password": "s3cret"}


def test_outputs_are_none_when_the_resource_does_not_exist(fake_run, module_dir):
    fake_run((0, "{}", ""))

    assert _terraform(module_dir).outputs() is None


def test_a_failed_plan_raises_the_classified_error(fake_run, module_dir):
    fake_run((ERROR, "", "Error: Unsupported argument"))

    with pytest.raises(TerraformPermanentError, match="Unsupported argument"):
        _terraform(module_dir).apply({})


def test_a_failed_apply_raises_the_classified_error(fake_run, module_dir):
    fake_run((CHANGES, "", ""), (1, "", "Error: Unsupported argument"))

    with pytest.raises(TerraformPermanentError, match="terraform apply failed"):
        _terraform(module_dir).apply({})
