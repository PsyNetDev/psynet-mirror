import sys
from unittest.mock import Mock

import pytest

from psynet.utils import TranslationNotFoundError, check_translation_is_available


def _check_missing_entry(monkeypatch, namespace, *, live=False):
    monkeypatch.setattr("psynet.experiment.in_deployment_package", lambda: live)
    if live:
        monkeypatch.setattr("psynet.deployment_info.read", lambda key: "live")
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


def test_missing_package_entry_is_tolerated_in_feature_branch_tests(monkeypatch):
    monkeypatch.setenv("CI_COMMIT_REF_NAME", "cursor/test-translation-policy")
    _check_missing_entry(monkeypatch, "psynet")


def test_missing_package_entry_raises_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(TranslationNotFoundError):
        _check_missing_entry(monkeypatch, "psynet")


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
    _check_missing_entry(monkeypatch, "experiment", live=True)
    assert isinstance(captured["error"], TranslationNotFoundError)
    assert captured["exc_info"][0] is TranslationNotFoundError
    assert captured["exc_info"][1] is captured["error"]
