import json
import time
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

MEDIA_HEADERS = {"wav": b"RIFF\x00\x00\x00\x00WAVE", "webm": b"\x1a\x45\xdf\xa3"}


def media_bytes(media_format, text):
    """Return the bytes the run_bot experiment's bot uploads."""
    return MEDIA_HEADERS[media_format] + text.encode()


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
        assert status["page"]["is_timeline_hold"] is False
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
        with open(file_name, "rb") as f:
            assert f.read() == media_bytes("wav", f"This is a recording from {bot.id}!")

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
        with open(response_files["cameraRecording"], "rb") as f:
            assert f.read() == media_bytes(
                "webm", f"This is a camera recording from bot {bot.id}."
            )
        with open(response_files["screenRecording"], "rb") as f:
            assert f.read() == media_bytes(
                "webm", f"This is a screen recording from bot {bot.id}."
            )

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


def test_render_page_requests_html_timeline(monkeypatch):
    """``render_pages=True`` must compile templates, not fetch a JSON snapshot."""
    seen = {}

    def fake_get(url, params=None, headers=None, **kwargs):
        seen["url"] = url
        seen["params"] = dict(params or {})
        seen["headers"] = dict(headers or {})
        response = SimpleNamespace(status_code=200, text="<html></html>")
        response.raise_for_status = lambda: None
        return response

    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.__dict__["_http_session"] = SimpleNamespace(get=fake_get)
    driver.experiment = SimpleNamespace(base_url="http://psynet.test")
    driver.participant_unique_id = "abc"
    driver._render_page()
    assert seen["url"] == "http://psynet.test/timeline"
    assert seen["params"] == {"unique_id": "abc"}
    assert seen["params"].get("mode") != "json"
    assert seen["headers"].get("Accept") != "application/json"


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

    driver.__dict__["_http_session"] = SimpleNamespace(post=fake_post)
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

    driver.__dict__["_http_session"] = SimpleNamespace(post=fake_post)
    monkeypatch.setattr(driver, "_fetch_status", fake_fetch)
    monkeypatch.setattr("psynet.participant.db.session.expire_all", lambda: None)

    with pytest.raises(RuntimeError, match="Synchronization problem detected"):
        driver._submit_response(driver.status, {})

    assert posted == ["hold-a"]


def test_submit_response_sends_hold_resume_for_timeline_holds(monkeypatch):
    """Parallel bots must not take blocking FOR UPDATE on an unready hold."""
    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.id = 7
    driver.experiment = SimpleNamespace(base_url="http://psynet.test")
    driver.response_files = {}
    driver.status = _driver_page_status("hold-a")
    driver.status["page"]["is_timeline_hold"] = True
    posted = []

    def fake_post(_url, data=None, files=None):
        posted.append(json.loads(data["json"]))
        return _driver_http_response({"submission": "approved"})

    driver.__dict__["_http_session"] = SimpleNamespace(post=fake_post)
    monkeypatch.setattr(driver, "_fetch_status", lambda: None)
    monkeypatch.setattr("psynet.participant.db.session.expire_all", lambda: None)

    driver._submit_response(driver.status, {})

    assert posted[0]["timeline_hold_resume"] is True


def test_submit_response_retries_structured_busy_like_timeline_gets(monkeypatch):
    """Hold-resume POST can hit skip's NOWAIT; bots must not fail on the first 503."""
    from psynet.participant import _BOT_TIMELINE_BUSY_ATTEMPTS

    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.id = 7
    driver.experiment = SimpleNamespace(base_url="http://psynet.test")
    driver.response_files = {}
    driver.status = _driver_page_status("hold-a")
    driver.status["page"]["is_timeline_hold"] = True
    calls = {"n": 0}

    def fake_post(_url, data=None, files=None):
        calls["n"] += 1
        if calls["n"] < _BOT_TIMELINE_BUSY_ATTEMPTS:
            return SimpleNamespace(
                status_code=503,
                json=lambda: {"status": "busy", "submission": "busy"},
                text='{"status": "busy", "submission": "busy"}',
                raise_for_status=lambda: None,
            )
        return _driver_http_response({"submission": "approved"})

    driver.__dict__["_http_session"] = SimpleNamespace(post=fake_post)
    monkeypatch.setattr(driver, "_fetch_status", lambda: None)
    monkeypatch.setattr("psynet.participant.db.session.expire_all", lambda: None)
    monkeypatch.setattr("psynet.participant.time.sleep", lambda s: None)

    driver._submit_response(driver.status, {})

    assert calls["n"] == _BOT_TIMELINE_BUSY_ATTEMPTS


@pytest.mark.parametrize("time_factor, poll", [(0, 0.1), (1, 0.5)])
def test_take_page_polls_timeline_hold_at_check_interval(
    monkeypatch, time_factor, poll
):
    """Paced bots spend the page's time, then poll a hold every ``check_interval``."""
    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.status = _driver_page_status("page-a")
    driver.status["status"] = "working"
    hold = _driver_page_status("hold-a")
    hold["status"] = "working"
    hold["page"].update(is_timeline_hold=True, time_estimate=3.0, check_interval=0.5)
    driver.response_files = {}
    sleeps = []

    def submit(*args, **kwargs):
        driver.status = hold
        driver.status_time_fetched = time.monotonic()

    monkeypatch.setattr(driver, "_submit_response", submit)
    monkeypatch.setattr("psynet.participant.time.sleep", lambda s: sleeps.append(s))
    driver.status_time_fetched = time.monotonic()

    for _ in range(3):
        driver.take_page(render_pages=False, time_factor=time_factor)

    assert sleeps == pytest.approx([time_factor, poll, poll, poll], abs=0.05)


def test_page_min_duration_follows_the_submit_enable_triggers():
    from psynet.modular_page import AudioMeterControl, AudioRecordControl
    from psynet.page import InfoPage

    record = AudioRecordControl(duration=4, bot_response_media="x.wav")
    assert InfoPage("Hi", time_estimate=1).min_duration == 0
    assert ModularPage("rec", "Sing", record, time_estimate=5).min_duration == 4
    meter = AudioMeterControl(min_time=2.5)
    assert ModularPage("meter", "Adjust", meter, time_estimate=5).min_duration == 2.5


@pytest.mark.parametrize(
    "time_factor, min_duration, expected_sleep",
    [(0, 5.0, 0), (1, 0.0, 2.0), (1, 5.0, 5.0), (3, 5.0, 6.0)],
)
def test_paced_bots_stay_on_a_page_for_at_least_its_min_duration(
    monkeypatch, time_factor, min_duration, expected_sleep
):
    driver = ParticipantDriver.__new__(ParticipantDriver)
    driver.status = _driver_page_status("page-a")
    driver.status["status"] = "working"
    driver.status["page"].update(time_estimate=2.0, min_duration=min_duration)
    driver.response_files = {}
    sleeps = []
    monkeypatch.setattr(driver, "_submit_response", lambda *args, **kwargs: None)
    monkeypatch.setattr("psynet.participant.time.sleep", sleeps.append)
    driver.status_time_fetched = time.monotonic()

    driver.take_page(render_pages=False, time_factor=time_factor)

    assert sleeps[0] == pytest.approx(expected_sleep, abs=0.05)
