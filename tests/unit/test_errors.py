import pytest

from reva_core.shared.errors import (
    ConfigurationError,
    PolicyDeniedError,
    ProviderError,
    ProviderErrorKind,
    RevaError,
    StorageError,
    SyncError,
    ToolExecutionError,
    ValidationError,
)


@pytest.mark.parametrize(
    "exc_type",
    [
        ConfigurationError,
        StorageError,
        PolicyDeniedError,
        ValidationError,
        ToolExecutionError,
        SyncError,
    ],
)
def test_all_domain_errors_are_reva_errors(exc_type):
    assert issubclass(exc_type, RevaError)


def test_provider_error_carries_kind():
    error = ProviderError(ProviderErrorKind.TIMEOUT, "timed out")
    assert error.kind == ProviderErrorKind.TIMEOUT
    assert str(error) == "timed out"
    assert isinstance(error, RevaError)


def test_provider_error_kind_covers_required_conditions():
    required = {
        "unavailable",
        "timeout",
        "invalid_response",
        "authentication_failure",
        "rate_limited",
    }
    actual = {kind.value for kind in ProviderErrorKind}
    assert actual == required
