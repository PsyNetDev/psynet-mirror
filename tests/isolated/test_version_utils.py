import pytest

from psynet.version import (
    check_installed_dallinger_version_is_recommended,
    is_development_version,
)


@pytest.mark.parametrize(
    "version,expected",
    [
        ("13.1.0a0", True),
        ("13.1.0a1", True),
        ("10.0.0b5", True),
        ("9.4.0a1", True),
        ("13.1.0", False),
        ("13.1.0rc1", False),
        ("v13.1.0a0", False),
        ("13.1.0a", False),
        ("13.1", False),
        ("13", False),
        ("13.1.0.0a0", False),
    ],
)
def test_is_development_version(version, expected):
    """
    Test that is_development_version correctly identifies development versions.

    Development versions are defined as three numbers (major.minor.patch)
    followed by exactly one letter and then numbers, e.g. "13.1.0a0".
    """
    assert is_development_version(version) == expected


def test_pinned_dallinger_version_is_recommended(monkeypatch):
    """Accept the Dallinger series required by the deployment-plan API."""
    monkeypatch.setattr("dallinger.version.__version__", "12.4.0a1")

    check_installed_dallinger_version_is_recommended()
