"""Domain errors raised below the Temporal layer.

Nothing here knows about Temporal. `orchestrator.activities` is the one place these are
turned into retryable or non-retryable activity failures, using `retryable`.
"""


class OrchestratorError(Exception):
    retryable = False


class ValidationError(OrchestratorError):
    """The request itself is wrong. Retrying the same request cannot succeed."""


class VerificationError(OrchestratorError):
    """The resource does not (yet) match the request. Often it is still starting."""

    retryable = True


class TerraformTransientError(OrchestratorError):
    """Terraform failed for a reason that usually clears on its own."""

    retryable = True


class TerraformPermanentError(OrchestratorError):
    """Terraform failed for a reason that needs a person: bad config, a conflict."""
