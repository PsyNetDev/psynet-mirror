import os

import pytest

from psynet.package_size import (
    DEFAULT_EXP_MAX_SIZE_MB,
    HEROKU_MAX_SLUG_MB,
    apply_default_exp_max_size_mb,
    get_exp_max_size_mb,
    package_size_limit_error,
)
from psynet.utils import working_directory


@pytest.fixture(autouse=True)
def _restore_exp_max_size_mb(monkeypatch):
    # Setting before deleting makes monkeypatch restore the original (possibly
    # absent) value, even after code under test writes the variable.
    monkeypatch.setenv("EXP_MAX_SIZE_MB", "0")
    monkeypatch.delenv("EXP_MAX_SIZE_MB")


def test_get_exp_max_size_mb_defaults_to_1024_without_mutating_environ(monkeypatch):
    monkeypatch.delenv("EXP_MAX_SIZE_MB", raising=False)
    assert get_exp_max_size_mb() == DEFAULT_EXP_MAX_SIZE_MB
    assert "EXP_MAX_SIZE_MB" not in os.environ


def test_get_exp_max_size_mb_reads_explicit_env(monkeypatch):
    monkeypatch.setenv("EXP_MAX_SIZE_MB", "256")
    assert get_exp_max_size_mb() == 256
    assert get_exp_max_size_mb(heroku=True) == 256


def test_get_exp_max_size_mb_rejects_non_integer_env(monkeypatch):
    monkeypatch.setenv("EXP_MAX_SIZE_MB", "1GB")
    with pytest.raises(ValueError, match="integer number of megabytes"):
        get_exp_max_size_mb()


def test_get_exp_max_size_mb_heroku_caps_at_slug_limit(monkeypatch):
    monkeypatch.delenv("EXP_MAX_SIZE_MB", raising=False)
    assert get_exp_max_size_mb(heroku=True) == HEROKU_MAX_SLUG_MB
    monkeypatch.setenv("EXP_MAX_SIZE_MB", "1024")
    assert get_exp_max_size_mb(heroku=True) == HEROKU_MAX_SLUG_MB


def test_apply_default_exp_max_size_mb_sets_env_once(monkeypatch):
    monkeypatch.delenv("EXP_MAX_SIZE_MB", raising=False)
    apply_default_exp_max_size_mb()
    assert os.environ["EXP_MAX_SIZE_MB"] == str(DEFAULT_EXP_MAX_SIZE_MB)
    monkeypatch.setenv("EXP_MAX_SIZE_MB", "200")
    apply_default_exp_max_size_mb()
    assert os.environ["EXP_MAX_SIZE_MB"] == "200"


def test_heroku_size_check_rejects_packages_over_slug_limit(tmp_path, monkeypatch):
    from psynet.experiment import Experiment

    monkeypatch.delenv("EXP_MAX_SIZE_MB", raising=False)

    class _FakeSource:
        size = 600 * 1000**2

        def __init__(self, _root):
            pass

    monkeypatch.setattr("dallinger.utils.ExperimentFileSource", _FakeSource)
    (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")

    with working_directory(tmp_path):
        Experiment.check_size()
        with pytest.raises(RuntimeError, match="Heroku"):
            Experiment.check_size(heroku=True)
        assert os.environ["EXP_MAX_SIZE_MB"] == str(DEFAULT_EXP_MAX_SIZE_MB)


def test_heroku_size_error_mentions_deployment_files_list():
    message = package_size_limit_error(600, 500, heroku=True)
    assert "dallinger deployment-files list" in message
    assert "500 MB" in message
    assert "deployment-plan" in message
    assert "built slug" in message


def test_heroku_size_error_cites_configured_limit_when_below_slug_cap():
    message = package_size_limit_error(300, 200, heroku=True)
    assert "200 MB" in message
    assert "EXP_MAX_SIZE_MB=200" in message
    assert "500 MB" in message


def test_size_error_names_a_custom_limit():
    message = package_size_limit_error(2500, 2000)
    assert "EXP_MAX_SIZE_MB=2000" in message
    assert "default of 1024 MB" in message
