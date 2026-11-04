from unittest.mock import Mock

import pytest
from dallinger.experiment import EXPERIMENT_ROUTE_REGISTRATIONS
from dallinger.experiment_server.dashboard import (
    User,
    dashboard,
    load_user_from_request,
)
from flask import Blueprint, Flask
from flask_login import LoginManager

from psynet.artifact import LocalArtifactStorage
from psynet.experiment import Experiment

LOGIN = {"Authorization": "Basic YWRtaW46c2VjcmV0"}  # admin:secret

DASHBOARD_EXPERIMENT_ROUTES = [
    "fail_node",
    "fail_info",
    "fail_trial",
    "grow_network",
    "call_async_post_grow_network",
]


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    app.config["ADMIN_USER"] = User(userid="admin", password="secret")
    login_manager = LoginManager(app)
    login_manager.user_loader(lambda user_id: None)
    login_manager.request_loader(load_user_from_request)
    app.register_blueprint(dashboard)
    experiment_routes = Blueprint("experiment_routes", __name__)
    for route in EXPERIMENT_ROUTE_REGISTRATIONS:
        if route["func_name"] in DASHBOARD_EXPERIMENT_ROUTES:
            experiment_routes.add_url_rule(
                route["rule"],
                endpoint=route["func_name"],
                view_func=getattr(Experiment, route["func_name"]),
                **dict(route["kwargs"]),
            )
    app.register_blueprint(experiment_routes)
    app.add_url_rule("/response", view_func=lambda: "ok", methods=["POST"])
    app.before_request(Experiment.before_request)
    return app.test_client()


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/dashboard/status/get?deployment_id=x&type=experiment"),
        ("POST", "/dashboard/archive/deployment?id=x"),
        ("POST", "/dashboard/restore/deployment?id=x"),
        ("POST", "/dashboard/update/recruitment?deployment_id=x"),
        ("POST", "/dashboard/comment/set/x"),
        ("GET", "/dashboard/comment/get/x"),
        ("GET", "/dashboard/export/trigger?assets=none"),
        ("GET", "/dashboard/export/preflight"),
        ("GET", "/dashboard/export/download?assets=none"),
        ("GET", "/dashboard/artifact/x/export.zip"),
        ("POST", "/dashboard/participants/pay-bonus"),
        ("POST", "/dashboard/participants/dismiss-bonus"),
        ("POST", "/dashboard/sync-groups/1/participant/1/fail"),
        ("POST", "/dashboard/sync-groups/1/participant/1/kick"),
        ("POST", "/dashboard/module"),
        ("POST", "/dashboard/module/tooltip"),
        ("GET", "/dashboard/module/progress_info"),
        ("POST", "/dashboard/module/update_spending_limits"),
        ("POST", "/dashboard/change_lucid_status?status=paused"),
        ("POST", "/node/1/fail"),
        ("POST", "/info/1/fail"),
        ("POST", "/trial/1/fail"),
        ("POST", "/network/1/grow"),
        ("POST", "/network/1/call_async_post_grow_network"),
    ],
)
def test_dashboard_routes_reject_anonymous_requests(client, method, path):
    assert client.open(path, method=method).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard/archive/deployment?id=x",
        "/dashboard/restore/deployment?id=x",
        "/dashboard/update/recruitment?deployment_id=x",
        "/dashboard/change_lucid_status?status=paused",
        "/dashboard/module",
        "/dashboard/module/tooltip",
        "/dashboard/module/update_spending_limits",
        "/node/1/fail",
        "/info/1/fail",
        "/trial/1/fail",
        "/network/1/grow",
        "/network/1/call_async_post_grow_network",
    ],
)
def test_data_changing_routes_refuse_get(client, path):
    assert client.get(path).status_code == 405


@pytest.mark.parametrize(
    "headers, status_code",
    [
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Sec-Fetch-Site": "same-site"}, 403),
        ({"Origin": "https://localhost"}, 403),
        ({"Origin": ""}, 403),
        ({"Sec-Fetch-Site": "same-origin"}, 401),
        ({"Origin": "http://localhost"}, 401),
        ({}, 401),
    ],
)
def test_dashboard_refuses_cross_site_posts(client, headers, status_code):
    path = "/dashboard/archive/deployment?id=x"
    assert client.post(path, headers=headers).status_code == status_code


def test_cross_site_posts_to_participant_routes_are_allowed(client):
    response = client.post("/response", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200


def test_logged_in_cross_site_posts_to_dallinger_routes_are_refused(client):
    headers = {**LOGIN, "Sec-Fetch-Site": "cross-site"}
    assert client.post("/node/1/fail", headers=headers).status_code == 403


@pytest.fixture
def experiment(monkeypatch, tmp_path):
    exp = Mock()
    exp._parse_status = Experiment._parse_status
    exp.artifact_storage = LocalArtifactStorage(str(tmp_path))
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: exp)
    monkeypatch.setattr(
        "psynet.experiment.render_template", lambda *args, **kwargs: kwargs["html"]
    )
    monkeypatch.setattr(
        "psynet.export.service.store_latest_archive", lambda zip_path: None
    )
    return exp


def test_export_trigger_only_builds_the_export_on_post(client, experiment):
    page = client.get("/dashboard/export/trigger?assets=none", headers=LOGIN)
    assert page.status_code == 200
    assert '<form method="post">' in page.text
    experiment.build_export_archive.assert_not_called()

    response = client.post(
        "/dashboard/export/trigger", data={"assets": "none"}, headers=LOGIN
    )
    assert response.status_code == 200
    assert response.json["assets"] == "none"
    experiment.build_export_archive.assert_called_once()

    response = client.post(
        "/dashboard/export/trigger", data={"assets": "none", "html": "1"}, headers=LOGIN
    )
    assert "Export built and stored" in response.text


def test_update_recruitment_rejects_invalid_deployment_ids(client, experiment):
    response = client.post(
        "/dashboard/update/recruitment",
        data={"deployment_id": "../x"},
        headers=LOGIN,
    )
    assert response.status_code == 400
