import pytest

from orchestrator.errors import TerraformPermanentError, TerraformTransientError
from orchestrator.terraform.classifier import classify


@pytest.mark.parametrize(
    "stderr",
    [
        "Error: Error acquiring the state lock\n\nError message: resource temporarily unavailable",
        "Error: Error pinging Docker server: Cannot connect to the Docker daemon at npipe://",
        "Error: Unable to read Docker image into resource: net/http: TLS handshake timeout",
        "Error: something nobody has seen before",
    ],
)
def test_transient_failures_are_retryable(stderr):
    assert isinstance(classify("apply", stderr), TerraformTransientError)


@pytest.mark.parametrize(
    "stderr",
    [
        "Error: Invalid value for variable\n\n  on variables.tf line 1:\nresource_id must be",
        'Error: Unsupported argument\n\nAn argument named "foo" is not expected here.',
        'Error: Unable to create container: Conflict. The container name "/pg-a" is already in use',
        "Error: Unable to read Docker image into resource: manifest for postgres:16.99 not found",
    ],
)
def test_failures_that_waiting_cannot_fix_are_permanent(stderr):
    assert isinstance(classify("apply", stderr), TerraformPermanentError)


def test_message_names_the_command_and_the_first_error():
    error = classify("apply", "some noise\nError: Unsupported argument\n\nmore detail")

    assert str(error) == "terraform apply failed: Unsupported argument"
