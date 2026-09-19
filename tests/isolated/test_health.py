from unittest.mock import Mock, patch

import pytest
from flask import Flask

from psynet.experiment import Experiment


def _health_response():
    with Flask(__name__).app_context():
        response = Experiment.health()
        return response.get_json(), response.status_code


def test_health_reports_ok_when_required_services_are_available():
    connection = Mock()
    connect = Mock()
    connect.return_value.__enter__ = Mock(return_value=connection)
    connect.return_value.__exit__ = Mock(return_value=False)

    with (
        patch("psynet.experiment.db.engine.connect", connect),
        patch("psynet.experiment.db.redis_conn.ping", return_value=True) as ping,
    ):
        body, status = _health_response()

    assert status == 200
    assert body == {"status": "ok"}
    connection.execute.assert_called_once()
    ping.assert_called_once_with()


@pytest.mark.parametrize("dependency", ["database", "redis"])
def test_health_reports_unavailable_without_exposing_error_details(dependency):
    connection = Mock()
    connect = Mock()
    connect.return_value.__enter__ = Mock(return_value=connection)
    connect.return_value.__exit__ = Mock(return_value=False)
    if dependency == "database":
        connection.execute.side_effect = RuntimeError("secret database detail")

    redis_error = RuntimeError("secret redis detail") if dependency == "redis" else None
    with (
        patch("psynet.experiment.db.engine.connect", connect),
        patch("psynet.experiment.db.redis_conn.ping", side_effect=redis_error),
    ):
        body, status = _health_response()

    assert status == 503
    assert body == {"status": "unavailable"}
    assert "secret" not in str(body)
