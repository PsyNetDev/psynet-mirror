import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from psynet.asset import Asset
from psynet.bot import BotDriver
from psynet.experiment import Request
from psynet.modular_page import ModularPage
from psynet.participant import ParticipantDriver
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Response


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("run_bot")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestRunBot:
    def test_run_bot(self):
        bot = BotDriver()

        # The first page is a simple multiple choice question,
        # and does not have any files to upload.

        # Check the _render_page function
        # We start with one request already, because the bot driver
        # makes a request to the /timeline endpoint when it is initialized.
        assert Request.query.filter_by(endpoint="/timeline").count() == 1
        bot._render_page()
        assert Request.query.filter_by(endpoint="/timeline").count() == 2

        # Check the _fetch_status function
        bot._fetch_status()
        status = bot.status
        response_files = bot.response_files
        assert status["status"] == "working"
        assert status["page"]["id"] == ["main", 0]
        assert status["page"]["label"] == "favourite_colour"
        assert status["page"]["time_estimate"] == 5
        assert status["page"]["bot_response"]["answer"] == "red"
        assert len(response_files) == 0

        # Check the _submit_response function
        bot._submit_response(status, response_files)
        assert Response.query.count() == 1

        # The second page is an audio recording page,
        # so the bot response involves uploading a file.

        # Check the _render_page function
        assert Request.query.filter_by(endpoint="/timeline").count() == 2
        bot._render_page()
        assert Request.query.filter_by(endpoint="/timeline").count() == 3

        # Check the _fetch_status function
        bot._fetch_status()
        status = bot.status
        response_files = bot.response_files
        assert status["page"]["id"] == ["main", 1]
        assert status["page"]["label"] == "record_audio"
        assert status["page"]["time_estimate"] == 5

        assert len(response_files) == 1
        file_name = response_files["audioRecording"]
        with open(file_name, "r") as f:
            assert f.read() == f"This is a recording from {bot.id}!"

        # Check the _submit_response function
        assert Asset.query.count() == 0
        bot._submit_response(status, response_files)
        assert Response.query.count() == 2
        assert Asset.query.count() == 1

        # Third page: video recording (camera and screen)
        assert Request.query.filter_by(endpoint="/timeline").count() == 3
        bot._render_page()
        assert Request.query.filter_by(endpoint="/timeline").count() == 4

        bot._fetch_status()
        status = bot.status
        response_files = bot.response_files
        assert status["page"]["id"] == ["main", 2]
        assert status["page"]["label"] == "record_video"
        assert status["page"]["time_estimate"] == 5

        assert set(response_files.keys()) == {"cameraRecording", "screenRecording"}
        with open(response_files["cameraRecording"], "r") as f:
            assert f.read() == f"This is a camera recording from bot {bot.id}."
        with open(response_files["screenRecording"], "r") as f:
            assert f.read() == f"This is a screen recording from bot {bot.id}."

        prev_response_count = Response.query.count()
        prev_asset_count = Asset.query.count()
        bot._submit_response(status, response_files)
        assert Response.query.count() == prev_response_count + 1
        assert Asset.query.count() == prev_asset_count + 2

    def test_get_current_page(self):
        bot = BotDriver()

        # We'll just check the first page for now, should be enough
        # to ensure that the method is working.
        page = bot.get_current_page()
        assert isinstance(page, ModularPage)
        assert page.label == "favourite_colour"


def test_advance_past_wait_pages_refreshes_status_when_server_already_advanced():
    """Last-arrival skip must refresh bot drivers, not leave cached hold copy."""
    from psynet.bot import advance_past_wait_pages

    bot = MagicMock()
    bot.get_current_page.return_value = SimpleNamespace(is_timeline_hold=False)
    advance_past_wait_pages([bot])
    bot.take_page.assert_not_called()
    bot.refresh_status.assert_called_once()


def test_advance_past_wait_pages_refreshes_before_each_wait_iteration():
    """A partner skipped mid-loop must not submit a stale wait-page uuid."""
    from psynet.bot import advance_past_wait_pages

    bot = MagicMock()

    def current_page():
        if bot.take_page.call_count:
            return SimpleNamespace(is_timeline_hold=False)
        return SimpleNamespace(is_timeline_hold=True)

    bot.get_current_page.side_effect = current_page
    advance_past_wait_pages([bot])
    assert bot.take_page.call_count == 1
    assert bot.refresh_status.call_count == 2


def _driver_page_status(page_uuid, answer="ok"):
    return {
        "page_uuid": page_uuid,
        "page": {
            "time_estimate": 1,
            "bot_response": {"answer": answer, "metadata": {}, "blobs": {}},
        },
    }


def _driver_http_response(body):
    return SimpleNamespace(
        status_code=200,
        json=lambda: body,
        raise_for_status=lambda: None,
    )


def test_submit_response_retries_once_when_the_page_uuid_rotated(monkeypatch):
    """Last-arrival skip can rotate page_uuid between status fetch and POST."""
    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.id = 7
    driver.experiment = SimpleNamespace(base_url="http://psynet.test")
    driver.response_files = {}
    driver.status = _driver_page_status("hold-a", "first")
    posted = []

    def fake_post(_url, data=None, files=None):
        payload = json.loads(data["json"])
        posted.append(payload["page_uuid"])
        if payload["page_uuid"] == "hold-a":
            return _driver_http_response(
                {
                    "submission": "rejected",
                    "message": "Synchronization problem detected.",
                }
            )
        return _driver_http_response({"submission": "approved"})

    def fake_fetch():
        driver.status = _driver_page_status("hold-b", "second")
        driver.response_files = {}
        driver.status_time_fetched = 0

    monkeypatch.setattr("psynet.participant.requests.post", fake_post)
    monkeypatch.setattr(driver, "_fetch_status", fake_fetch)
    monkeypatch.setattr("psynet.participant.db.session.expire_all", lambda: None)

    driver._submit_response(driver.status, {})

    assert posted == ["hold-a", "hold-b"]


def test_submit_response_does_not_retry_when_the_page_uuid_is_unchanged(
    monkeypatch,
):
    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.id = 7
    driver.experiment = SimpleNamespace(base_url="http://psynet.test")
    driver.response_files = {}
    driver.status = _driver_page_status("hold-a")
    posted = []

    def fake_post(_url, data=None, files=None):
        payload = json.loads(data["json"])
        posted.append(payload["page_uuid"])
        return _driver_http_response(
            {
                "submission": "rejected",
                "message": "Synchronization problem detected.",
            }
        )

    def fake_fetch():
        driver.status = _driver_page_status("hold-a")
        driver.response_files = {}
        driver.status_time_fetched = 0

    monkeypatch.setattr("psynet.participant.requests.post", fake_post)
    monkeypatch.setattr(driver, "_fetch_status", fake_fetch)
    monkeypatch.setattr("psynet.participant.db.session.expire_all", lambda: None)

    with pytest.raises(RuntimeError, match="Synchronization problem detected"):
        driver._submit_response(driver.status, {})

    assert posted == ["hold-a"]
