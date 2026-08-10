"""Security invariant #2: network listeners bind only to loopback."""

import pytest

from reva_core.config.settings import load_settings
from reva_core.shared.errors import ConfigurationError


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com", ""])
def test_non_loopback_host_is_rejected(host):
    with pytest.raises(ConfigurationError):
        load_settings(_env_file=None, api_host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST"])
def test_loopback_hosts_are_accepted(host):
    settings = load_settings(_env_file=None, api_host=host)
    assert settings.api_host == host
