import pytest
from dallinger.config import get_config

from psynet.experiment import get_experiment
from psynet.pytest_psynet import path_to_test_experiment
from psynet.utils import get_from_config


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_config(in_experiment_directory):
    _recruiter = get_from_config("recruiter")
    assert _recruiter == "generic"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_inplace_timeline_transitions_default(in_experiment_directory):
    get_experiment()
    config = get_config()

    assert config.get("inplace_timeline_transitions") is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_legacy_js_var_globals_default(in_experiment_directory):
    get_experiment()
    config = get_config()

    assert config.get("legacy_js_var_globals") == "warn"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_legacy_js_var_globals_rejects_invalid_mode(in_experiment_directory):
    get_experiment()
    config = get_config()

    with pytest.raises(ValueError, match="legacy_js_var_globals"):
        config.set("legacy_js_var_globals", "invalid")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_secrets(in_experiment_directory):
    get_experiment()
    config = get_config()

    assert config.get("auto_recruit") is not None
    assert "auto_recruit" in config.as_dict()

    for secret in [
        "lab_recruiter_auth_token",
        "lucid_api_key",
        "lucid_sha1_hashing_key",
    ]:
        config.set(secret, "my-secret")
        assert config.get(secret) is not None
        assert secret not in config.as_dict()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_warns_when_experiment_config_is_overridden(in_experiment_directory, caplog):
    import logging

    exp = get_experiment()
    config = get_config()

    # Simulate a higher-priority runtime write overriding a value set in
    # experiment.py.
    with config.override({"min_accumulated_reward_for_abort": 0.99}):
        with caplog.at_level(logging.WARNING):
            exp.check_config()

    assert "min_accumulated_reward_for_abort" in caplog.text
    assert "overridden" in caplog.text
    assert "0.15" in caplog.text
    assert "0.99" in caplog.text


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_override_warning_redacts_sensitive_values(
    in_experiment_directory, caplog, monkeypatch
):
    import logging

    exp = get_experiment()
    config = get_config()

    monkeypatch.setattr(
        type(exp),
        "config",
        {**exp.config, "dashboard_password": "my-secret-password"},
    )
    with config.override({"dashboard_password": "another-secret"}):
        with caplog.at_level(logging.WARNING):
            exp.check_config()

    assert "dashboard_password" in caplog.text
    assert "overridden" in caplog.text
    assert "my-secret-password" not in caplog.text
    assert "another-secret" not in caplog.text


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_no_override_warning_when_values_match(in_experiment_directory, caplog):
    import logging

    exp = get_experiment()

    with caplog.at_level(logging.WARNING):
        exp.check_config()

    assert "overridden" not in caplog.text


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_experiment_config_reaches_processes_that_change_directory(
    in_experiment_directory, tmp_path, monkeypatch
):
    # Regression test for https://gitlab.com/PsyNetDev/PsyNet/-/issues/1040:
    # values set in ``Experiment.config`` (e.g. dashboard credentials) must be
    # seen by every process of an experiment, including processes whose config
    # is only loaded after the current working directory has changed away from
    # the experiment directory. Previously such processes silently skipped the
    # experiment's config defaults and resolved different values, which caused
    # e.g. bots to authenticate with credentials the web server did not expect.
    import os

    import dallinger.config as dallinger_config

    get_experiment()  # Ensures the experiment package is initialized.

    saved_config = dallinger_config.config
    original_cwd = os.getcwd()
    # Isolate the test from any real ~/.dallingerconfig.
    monkeypatch.setenv("HOME", str(tmp_path))
    os.chdir(tmp_path)
    try:
        # Simulate a fresh process by discarding the cached config.
        dallinger_config.config = None
        config = dallinger_config.get_config(load=True)
        assert config.get("min_accumulated_reward_for_abort") == 0.15
    finally:
        dallinger_config.config = saved_config
        os.chdir(original_cwd)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_experiment_config_overrides_dallingerconfig(
    in_experiment_directory, tmp_path, monkeypatch
):
    # Values set in ``Experiment.config`` are the experimenter's explicit
    # decisions: a (possibly stale) value in ~/.dallingerconfig must not
    # override them.
    import dallinger.config as dallinger_config

    get_experiment()  # Ensures the experiment package is initialized.

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".dallingerconfig").write_text(
        "[Parameters]\nmin_accumulated_reward_for_abort = 0.99\n"
    )

    saved_config = dallinger_config.config
    try:
        # Simulate a fresh process by discarding the cached config.
        dallinger_config.config = None
        config = dallinger_config.get_config(load=True)
        assert config.get("min_accumulated_reward_for_abort") == 0.15
    finally:
        dallinger_config.config = saved_config


def test_psynet_defaults_stay_low_priority_outside_experiment(tmp_path, monkeypatch):
    # runtime_init.ensure_runtime patches Configuration.load to inject PsyNet's
    # baseline defaults into processes without an experiment (e.g. CLI
    # tooling running outside an experiment directory). Those defaults
    # must stay low priority: user-level configuration such as
    # ~/.dallingerconfig must still override them.
    import sys

    import dallinger.config as dallinger_config

    from psynet.runtime_init import ensure_runtime

    monkeypatch.delitem(sys.modules, "dallinger_experiment", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".dallingerconfig").write_text("[Parameters]\nwage_per_hour = 12.5\n")
    monkeypatch.chdir(tmp_path)
    ensure_runtime()

    saved_config = dallinger_config.config
    try:
        dallinger_config.config = None
        config = dallinger_config.get_config(load=True)
        # The PsyNet defaults layer was applied...
        assert config.get("notifier") == "logger"
        # ...but stays below ~/.dallingerconfig.
        assert config.get("wage_per_hour") == 12.5
    finally:
        dallinger_config.config = saved_config


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_prolific_screen_out_is_no_longer_supported(in_experiment_directory):
    get_experiment()
    config = get_config()

    with pytest.raises(ValueError, match="Prolific no longer supports"):
        config.set("prolific_enable_screen_out", True)
