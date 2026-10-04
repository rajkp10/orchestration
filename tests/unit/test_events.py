import pytest

from orchestrator.errors import ValidationError
from orchestrator.events import parse_event
from orchestrator.models import Action


def _payload(**overrides):
    payload = {
        "request_id": "req-1",
        "type": "db.postgres.provision",
        "resource_id": "orders",
        "params": {"version": "16.3"},
    }
    payload.update(overrides)
    return payload


def test_splits_type_into_resource_type_and_action():
    event = parse_event(_payload())

    assert event.resource_type == "db.postgres"
    assert event.action is Action.PROVISION
    assert event.event_type == "db.postgres.provision"
    assert event.params == {"version": "16.3"}


def test_params_are_optional():
    payload = _payload(type="db.postgres.decommission")
    del payload["params"]

    assert parse_event(payload).params == {}


@pytest.mark.parametrize("missing", ["request_id", "type", "resource_id"])
def test_rejects_missing_field(missing):
    payload = _payload()
    del payload[missing]

    with pytest.raises(ValidationError, match=missing):
        parse_event(payload)


def test_rejects_request_id_that_is_not_a_safe_file_name():
    # The request id becomes the workflow id and the name of the result file.
    with pytest.raises(ValidationError, match="request_id"):
        parse_event(_payload(request_id="../../etc/passwd"))


def test_rejects_unknown_action():
    with pytest.raises(ValidationError, match="reboot"):
        parse_event(_payload(type="db.postgres.reboot"))


def test_rejects_type_without_a_resource_type():
    with pytest.raises(ValidationError, match="provision"):
        parse_event(_payload(type="provision"))
