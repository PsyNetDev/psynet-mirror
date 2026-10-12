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
