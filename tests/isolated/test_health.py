from unittest.mock import Mock, patch

import pytest
from flask import Flask

from psynet.experiment import Experiment


def _health_response():
    with Flask(__name__).app_context():
        response = Experiment.health()
        return response.get_json(), response.status_code


def _available_services():
    connection = Mock()
    connect = Mock()
    connect.return_value.__enter__ = Mock(return_value=connection)
    connect.return_value.__exit__ = Mock(return_value=False)
    return connection, connect


def test_health_reports_ok_when_required_services_are_available():
    connection, connect = _available_services()

    with (
        patch("psynet.experiment.db.engine.connect", connect),
        patch("psynet.experiment.db.redis_conn.ping", return_value=True) as ping,
        patch("psynet.experiment.get_config", side_effect=RuntimeError("no config")),
    ):
        body, status = _health_response()

    assert status == 200
    assert body == {"status": "ok"}
    connection.execute.assert_called_once()
    ping.assert_called_once_with()


def test_health_includes_public_experiment_snapshot():
    _, connect = _available_services()
    config = Mock()
    config.get.side_effect = lambda key, default=None: {
        "title": "Melody Origin Classification",
        "label": "melody-origin",
        "experimenter_name": "David Whyatt",
    }.get(key, default)
    query = Mock()
    query.filter.return_value.count.return_value = 17

    with (
        patch("psynet.experiment.db.engine.connect", connect),
        patch("psynet.experiment.db.redis_conn.ping", return_value=True),
        patch("psynet.experiment.get_config", return_value=config),
        patch("psynet.experiment.redis_vars.get", return_value="recruiting"),
        patch("psynet.experiment.Request.query", query),
    ):
        body, status = _health_response()

    assert status == 200
    assert body == {
        "status": "ok",
        "title": "Melody Origin Classification",
        "label": "melody-origin",
        "experimenter_name": "David Whyatt",
        "recruitment_status": "recruiting",
        "requests_last_hour": 17,
    }


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
