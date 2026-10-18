import pytest

from psynet.notifier import LoggerNotifier, Notifier


def test_logger_notifier_redacts_dashboard_password():
    args = (
        "Experiment dashboard",
        "http://localhost:5000/dashboard",
        "admin",
        "s3cr3t",
    )
    assert "s3cr3t" in Notifier.format_credentials(*args)

    message = LoggerNotifier.format_credentials(*args)
    assert "s3cr3t" not in message
    assert "Username: `admin`" in message
    assert "Password: `<redacted>`" in message


@pytest.mark.parametrize(
    "ingress, logs_command, expected",
    [
        (None, None, "https://logs.lab"),
        ("classic", None, "https://logs.lab"),
        ("cloudflare", "ssh lab logs", "`ssh lab logs`"),
        ("cloudflare", None, "printed at the end of the deployment"),
    ],
)
def test_logs_message_follows_the_app_ingress(
    monkeypatch, ingress, logs_command, expected
):
    info = {"server": "lab", "ingress": ingress, "logs_command": logs_command}
    monkeypatch.setattr("psynet.deployment_info.read_all", lambda: info)
    monkeypatch.setattr(
        "psynet.notifier.get_config", lambda: {"dashboard_password": "pw"}
    )

    message = Notifier().logs_message

    assert expected in message
    assert ("Dozzle" in message) is (ingress != "cloudflare")
