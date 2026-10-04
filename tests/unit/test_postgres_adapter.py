import pytest

from orchestrator.errors import ValidationError, VerificationError
from orchestrator.models import Action, LifecycleEvent
from orchestrator.platforms.postgres import PostgresAdapter
from orchestrator.platforms.registry import get_adapter

adapter = PostgresAdapter()

CURRENT = {
    "resource_id": "orders",
    "postgres_version": "16.3",
    "env": "dev",
    "host_port": 32768,
    "password": "not-a-real-password",
}


def _event(action, resource_id="orders", **params):
    return LifecycleEvent(
        request_id="req-1",
        resource_type="db.postgres",
        action=action,
        resource_id=resource_id,
        params=params,
    )


def test_registry_resolves_postgres():
    assert isinstance(get_adapter("db.postgres"), PostgresAdapter)


def test_registry_rejects_unknown_platform():
    with pytest.raises(ValidationError, match="db.oracle"):
        get_adapter("db.oracle")


def test_workspace_is_per_resource():
    assert adapter.workspace(_event(Action.PROVISION)) == "pg-orders"


def test_module_dir_exists():
    assert (adapter.module_dir / "main.tf").is_file()


def test_provision_of_new_resource_is_valid():
    adapter.validate(_event(Action.PROVISION, version="16.3"), None)


def test_provision_resent_at_same_version_is_valid():
    # Lets a half-finished provision converge instead of being stuck.
    adapter.validate(_event(Action.PROVISION, version="16.3"), CURRENT)


def test_provision_of_existing_resource_at_other_version_is_rejected():
    with pytest.raises(ValidationError, match="already exists"):
        adapter.validate(_event(Action.PROVISION, version="16.4"), CURRENT)


@pytest.mark.parametrize("version", [None, "16", "latest", "16.3.1"])
def test_provision_needs_a_major_minor_version(version):
    params = {} if version is None else {"version": version}
    with pytest.raises(ValidationError, match="version"):
        adapter.validate(_event(Action.PROVISION, **params), None)


def test_rejects_bad_resource_id():
    with pytest.raises(ValidationError, match="resource_id"):
        adapter.validate(_event(Action.PROVISION, resource_id="Orders DB", version="16.3"), None)


def test_patch_to_newer_minor_is_valid():
    adapter.validate(_event(Action.PATCH, version="16.4"), CURRENT)


def test_patch_of_missing_resource_is_rejected():
    with pytest.raises(ValidationError, match="does not exist"):
        adapter.validate(_event(Action.PATCH, version="16.4"), None)


def test_patch_downgrade_is_rejected():
    with pytest.raises(ValidationError, match="downgrade"):
        adapter.validate(_event(Action.PATCH, version="16.2"), CURRENT)


def test_patch_major_bump_is_rejected():
    with pytest.raises(ValidationError, match="major"):
        adapter.validate(_event(Action.PATCH, version="17.0"), CURRENT)


def test_decommission_is_valid_whether_or_not_the_resource_exists():
    adapter.validate(_event(Action.DECOMMISSION), CURRENT)
    adapter.validate(_event(Action.DECOMMISSION), None)


def test_tf_vars_for_provision():
    tf_vars = adapter.tf_vars(_event(Action.PROVISION, version="16.3", env="staging"), None)

    assert tf_vars == {"resource_id": "orders", "postgres_version": "16.3", "env": "staging"}


def test_tf_vars_for_patch_keep_the_recorded_env_and_port():
    # The patch replaces the container; pinning the port it already has keeps the
    # instance's address stable for its clients.
    tf_vars = adapter.tf_vars(_event(Action.PATCH, version="16.4"), CURRENT)

    assert tf_vars == {
        "resource_id": "orders",
        "postgres_version": "16.4",
        "env": "dev",
        "host_port": "32768",
    }


def test_tf_vars_for_decommission_describe_the_existing_resource():
    tf_vars = adapter.tf_vars(_event(Action.DECOMMISSION), CURRENT)

    assert tf_vars == {
        "resource_id": "orders",
        "postgres_version": "16.3",
        "env": "dev",
        "host_port": "32768",
    }


def test_tf_vars_for_decommission_of_unrecorded_resource_are_still_complete():
    # A provision that failed part-way leaves resources in state but no outputs, and
    # destroy must still be able to run against it.
    tf_vars = adapter.tf_vars(_event(Action.DECOMMISSION), None)

    assert tf_vars == {"resource_id": "orders", "postgres_version": "0.0", "env": "dev"}


def test_public_outputs_leave_out_the_password():
    public = adapter.public_outputs(CURRENT)

    assert "password" not in public
    assert public["host_port"] == 32768


def test_simulated_verify_failure_raises():
    event = _event(Action.PATCH, version="16.4", simulate_verify_failure=True)

    with pytest.raises(VerificationError, match="simulated"):
        adapter.verify(event, CURRENT)
