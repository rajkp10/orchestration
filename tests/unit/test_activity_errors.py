import pytest
from temporalio.exceptions import ApplicationError

from orchestrator.activities import translate_errors
from orchestrator.errors import (
    TerraformPermanentError,
    TerraformTransientError,
    ValidationError,
    VerificationError,
)


def _raising(error):
    @translate_errors
    def fn():
        raise error

    return fn


@pytest.mark.parametrize("error", [ValidationError("bad"), TerraformPermanentError("bad")])
def test_errors_a_person_must_fix_are_not_retried(error):
    with pytest.raises(ApplicationError) as raised:
        _raising(error)()

    assert raised.value.non_retryable
    assert raised.value.type == type(error).__name__
    assert raised.value.message == "bad"


@pytest.mark.parametrize("error", [VerificationError("wait"), TerraformTransientError("wait")])
def test_errors_that_may_clear_are_retried(error):
    with pytest.raises(ApplicationError) as raised:
        _raising(error)()

    assert not raised.value.non_retryable


def test_unexpected_errors_pass_through_unchanged():
    with pytest.raises(KeyError):
        _raising(KeyError("bug"))()
