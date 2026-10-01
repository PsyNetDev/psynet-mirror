import pytest
from dallinger.experiment_server.dashboard import dashboard
from flask import Blueprint, Flask
from flask_login import LoginManager

from psynet.experiment import Experiment

DASHBOARD_EXPERIMENT_ROUTES = [
    ("/module/progress_info", "get_progress_info"),
    ("/module/update_spending_limits", "update_spending_limits"),
    ("/change_lucid_status", "change_lucid_status"),
]


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    LoginManager(app).user_loader(lambda user_id: None)
    app.register_blueprint(dashboard)
    experiment_routes = Blueprint("experiment_routes", __name__)
    for rule, func_name in DASHBOARD_EXPERIMENT_ROUTES:
        experiment_routes.add_url_rule(
            rule,
            endpoint=func_name,
            view_func=getattr(Experiment, func_name),
            methods=["GET", "POST"],
        )
    app.register_blueprint(experiment_routes)
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
        ("GET", "/module/progress_info"),
        ("POST", "/module/update_spending_limits"),
        ("GET", "/change_lucid_status?status=paused"),
    ],
)
def test_dashboard_routes_reject_anonymous_requests(client, method, path):
    assert client.open(path, method=method).status_code == 401
