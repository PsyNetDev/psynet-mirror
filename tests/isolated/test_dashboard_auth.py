import pytest
from dallinger.experiment_server.dashboard import dashboard
from flask import Flask
from flask_login import LoginManager

import psynet.experiment  # noqa: F401 (registers PsyNet's dashboard routes)


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    LoginManager(app).user_loader(lambda user_id: None)
    app.register_blueprint(dashboard)
    return app.test_client()


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/dashboard/status/get?deployment_id=x&type=experiment"),
        ("GET", "/dashboard/archive/deployment?id=x"),
        ("GET", "/dashboard/restore/deployment?id=x"),
        ("GET", "/dashboard/update/recruitment?deployment_id=x"),
        ("POST", "/dashboard/comment/set/x"),
        ("GET", "/dashboard/comment/get/x"),
        ("GET", "/dashboard/export/trigger?assets=none"),
        ("POST", "/dashboard/participants/pay-bonus"),
        ("POST", "/dashboard/participants/dismiss-bonus"),
        ("POST", "/dashboard/sync-groups/1/participant/1/fail"),
        ("POST", "/dashboard/sync-groups/1/participant/1/kick"),
    ],
)
def test_dashboard_routes_reject_anonymous_requests(client, method, path):
    assert client.open(path, method=method).status_code == 401
