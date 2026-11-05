import json
from types import SimpleNamespace

import pytest
from flask import Flask

from psynet.api import EXPOSED_FUNCTIONS
from psynet.experiment import Experiment


@pytest.mark.parametrize("page_uuid", [1, None, ["x"], {"x": 1}])
def test_response_route_refuses_a_non_string_page_uuid(page_uuid):
    payload = {"participant_id": 1, "page_uuid": page_uuid, "metadata": {}}
    with Flask(__name__).test_request_context(
        "/response", method="POST", data={"json": json.dumps(payload)}
    ):
        response = Experiment.route_response()

    assert response.status_code == 400


@pytest.mark.parametrize(
    "remote_addr, headers, local",
    [
        ("127.0.0.1", {}, True),
        ("::1", {}, True),
        ("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"}, False),
        ("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"}, False),
        ("203.0.113.9", {}, False),
    ],
)
def test_tunnelled_requests_do_not_count_as_local(remote_addr, headers, local):
    from psynet.experiment import _is_direct_local_request

    with Flask(__name__).test_request_context(
        "/dashboard/export/download",
        headers=headers,
        environ_base={"REMOTE_ADDR": remote_addr},
    ):
        assert _is_direct_local_request() is local


def test_api_route_sends_strings_as_plain_text(monkeypatch):
    monkeypatch.setitem(EXPOSED_FUNCTIONS, "echo", lambda name: f"Hello {name}!")
    with Flask(__name__).test_request_context("/api/echo?name=<script>x</script>"):
        response = Experiment.custom_route("echo")

    assert response.mimetype == "text/plain"
    assert response.get_data(as_text=True) == "Hello <script>x</script>!"


@pytest.mark.parametrize(
    "configured, query, valid",
    [
        (
            {"dashboard_user": "admin", "dashboard_password": "pw"},
            "?dashboard_user=admin&dashboard_password=pw",
            True,
        ),
        (
            {"dashboard_user": "admin", "dashboard_password": "pw"},
            "?dashboard_user=admin&dashboard_password=x",
            False,
        ),
        (
            {"dashboard_user": "admin", "dashboard_password": None},
            "?dashboard_user=admin",
            False,
        ),
        ({"dashboard_user": None, "dashboard_password": None}, "", False),
    ],
)
def test_basic_data_credentials(monkeypatch, configured, query, valid):
    monkeypatch.setattr(
        "psynet.experiment.get_config",
        lambda: SimpleNamespace(get=lambda key, default=None: configured[key]),
    )
    with Flask(__name__).test_request_context("/basic_data" + query) as context:
        assert (
            Experiment.request_contains_valid_dashboard_credentials(context.request)
            is valid
        )
