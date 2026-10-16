import sys
from unittest.mock import Mock

import pytest

from psynet.utils import TranslationNotFoundError, check_translation_is_available


def _check_missing_entry(monkeypatch, namespace, *, mode=None):
    """Look up a missing catalog entry, as if running in deployment ``mode``.

    ``mode=None`` means running outside a deployment package.
    """
    monkeypatch.setattr(
        "psynet.experiment.in_deployment_package", lambda: mode is not None
    )
    monkeypatch.setattr("psynet.deployment_info.read", lambda key: mode)
    monkeypatch.setattr(
        "psynet.utils.REGISTERED_TRANSLATIONS",
        {namespace: {"de": []}},
    )
    check_translation_is_available(
        "a string that is not in the catalog",
        "final-page-rewards",
        "de",
        namespace,
    )


@pytest.mark.parametrize("mode", [None, "debug"])
def test_missing_package_entry_is_tolerated_in_debug(monkeypatch, mode):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    _check_missing_entry(monkeypatch, "psynet", mode=mode)


def test_missing_package_entry_is_tolerated_in_feature_branch_tests(monkeypatch):
    monkeypatch.setenv("CI_COMMIT_REF_NAME", "cursor/test-translation-policy")
    _check_missing_entry(monkeypatch, "psynet")


def test_missing_package_entry_raises_in_sandbox(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(TranslationNotFoundError):
        _check_missing_entry(monkeypatch, "psynet", mode="sandbox")


def test_missing_package_entry_raises_on_release_branch(monkeypatch):
    monkeypatch.setenv("CI_COMMIT_REF_NAME", "release-13.4")
    with pytest.raises(TranslationNotFoundError):
        _check_missing_entry(monkeypatch, "psynet")


def test_missing_experiment_entry_always_raises(monkeypatch):
    with pytest.raises(TranslationNotFoundError):
        _check_missing_entry(monkeypatch, "experiment")


def test_missing_entry_is_reported_but_tolerated_in_live_experiment(monkeypatch):
    captured = {}

    def report_error(error):
        captured["error"] = error
        captured["exc_info"] = sys.exc_info()

    experiment = Mock(report_error=report_error)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    _check_missing_entry(monkeypatch, "experiment", mode="live")
    assert isinstance(captured["error"], TranslationNotFoundError)
    assert captured["exc_info"][0] is TranslationNotFoundError
    assert captured["exc_info"][1] is captured["error"]
