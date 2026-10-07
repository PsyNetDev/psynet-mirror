"""The recorded experimenter is the account that launched the process."""

import getpass

from psynet.experiment import Experiment


def test_get_username_uses_the_process_account(monkeypatch):
    monkeypatch.setattr(getpass, "getuser", lambda: "ada")

    assert Experiment.get_username() == "ada"


def test_get_username_ignores_the_docker_daemon_login(monkeypatch):
    def missing_account():
        raise KeyError(0)

    monkeypatch.setattr(getpass, "getuser", missing_account)
    monkeypatch.setattr("os.getlogin", lambda: "root")

    assert Experiment.get_username() == "unknown"
