import pytest

from psynet.version import (
    check_installed_dallinger_version_is_recommended,
    is_development_version,
    is_release_version_specifier,
)


@pytest.mark.parametrize(
    "specified,expected",
    [
        ("v14.0.0", True),
        ("v14.0.0rc2", True),
        ("14.0.0", True),
        ("14.0.0rc2", True),
        ("vocal-fixes", False),
        ("v14", False),
        ("master", False),
        ("45f317688af59350f9a6f3052fd73076318f2775", False),
    ],
)
def test_is_release_version_specifier(specified, expected):
    assert is_release_version_specifier(specified) is expected


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
