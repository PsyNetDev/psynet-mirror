"""SPA contract errors should be visible during local testing."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import psynet
from psynet.experiment import Experiment
from psynet.modular_page import Control, ModularPage, Prompt
from psynet.participant import (
    _extract_server_error_details,
    _raise_for_status_with_server_details,
    _retry_busy_http,
)
from psynet.timeline import (
    _SPA_INCOMPATIBILITY_MARKER,
    Page,
    Timeline,
    _format_spa_incompatibility_message,
)


def test_check_static_spa_contracts_fails_before_bots(monkeypatch):
    page = Page(
        label="dogfood_legacy",
        time_estimate=5,
        template_str='{% extends "timeline-page.html" %}',
    )
    experiment = MagicMock()
    experiment.timeline = Timeline(page)
    monkeypatch.setattr(
        "psynet.utils.get_config",
        lambda: SimpleNamespace(get=lambda key, default=None: True),
    )

    with pytest.raises(
        ValueError,
        match=r"error codes: complete_template",
    ):
        Experiment._check_static_spa_contracts(experiment)


def test_check_static_spa_contracts_surfaces_non_template_codes_without_app_context(
    monkeypatch,
):
    class CustomControl(Control):
        external_template = "custom-control.html"
        macro = "control"

    with pytest.warns(FutureWarning, match="js_links is deprecated"):
        page = ModularPage(
            "dogfood_modular",
            Prompt("Hi!"),
            CustomControl(),
            time_estimate=5,
            js_links=["/static/legacy.js"],
        )
    experiment = MagicMock()
    experiment.timeline = Timeline(page)
    monkeypatch.setattr(
        "psynet.utils.get_config",
        lambda: SimpleNamespace(get=lambda key, default=None: True),
    )

    with pytest.raises(ValueError, match=r"error codes: legacy_js_links"):
        Experiment._check_static_spa_contracts(experiment)


def test_extract_server_error_details_finds_spa_message():
    message = _format_spa_incompatibility_message(
        "dogfood_legacy", ["complete_template"]
    )
    body = f"""
    <html><body><pre>
    ValueError: {message}
    </pre></body></html>
    """

    details = _extract_server_error_details(body)
    assert "error codes: complete_template" in details
    assert "requires_full_page_reload=True" in details
    assert _SPA_INCOMPATIBILITY_MARKER in details


def test_extract_server_error_details_falls_back_to_value_error():
    body = 'ValueError: something unrelated went wrong\n  File "app.py", line 1'

    details = _extract_server_error_details(body)
    assert details == "ValueError: something unrelated went wrong"


def test_raise_for_status_includes_server_error_details():
    response = MagicMock()
    response.text = "ValueError: " + _format_spa_incompatibility_message(
        "dogfood_legacy", ["complete_template"]
    )
    response.raise_for_status.side_effect = requests.HTTPError(
        "500 Server Error", response=response
    )

    with pytest.raises(
        requests.HTTPError,
        match=r"(?s)Server error details:.*complete_template.*"
        + re.escape(_SPA_INCOMPATIBILITY_MARKER),
    ):
        _raise_for_status_with_server_details(response)


def _http_response(status_code, body=None, text=""):
    response = SimpleNamespace(status_code=status_code, text=text)
    if body is not None:
        response.json = lambda: body
        if not text:
            response.text = json.dumps(body)
    else:

        def _no_json():
            raise ValueError("No JSON")

        response.json = _no_json
    response.raise_for_status = lambda: None
    return response


def _busy():
    return _http_response(503, {"status": "busy", "submission": "busy"})


def test_retry_busy_http_retries_structured_busy_503_until_success():
    responses = [_busy(), _busy(), _busy(), _http_response(200)]

    result = _retry_busy_http(lambda: responses.pop(0), sleep=lambda s: None)

    assert result.status_code == 200
    assert responses == []


def test_retry_busy_http_gives_up_after_about_ten_seconds():
    slept = []

    result = _retry_busy_http(_busy, sleep=slept.append)

    assert result.status_code == 503
    assert 7 <= sum(slept) <= 10


def test_bot_and_browser_busy_retry_schedules_match():
    from psynet.participant import _BUSY_RETRY_DELAYS_S, _BUSY_RETRY_WINDOW_S

    js = (Path(psynet.__file__).parent / "resources/scripts/psynet.js").read_text()
    source = re.search(
        r"psynet\.busyRetryDelayMs = function[\s\S]*?\n    \};", js
    ).group(0)
    delays = re.search(r"const delays = \[([^\]]*)\]", source).group(1)
    window = re.search(r"elapsedMs \+ delay > (\d+)", source).group(1)

    assert [int(d) / 1000 for d in delays.split(",")] == list(_BUSY_RETRY_DELAYS_S)
    assert int(window) / 1000 == _BUSY_RETRY_WINDOW_S


def test_retry_busy_http_counts_slow_busy_replies_towards_the_window(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("psynet.participant.time.monotonic", lambda: clock[0])

    def slow_busy():
        clock[0] += 5
        return _busy()

    def sleep(seconds):
        clock[0] += seconds

    _retry_busy_http(slow_busy, sleep=sleep)

    assert clock[0] < 15


def test_retry_busy_http_does_not_retry_generic_503():
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        return _http_response(503, text="gateway timeout")

    result = _retry_busy_http(send)

    assert result.status_code == 503
    assert calls["n"] == 1


def test_retry_busy_http_does_not_retry_malformed_503():
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        return _http_response(503, text="{not-json")

    result = _retry_busy_http(send)

    assert result.status_code == 503
    assert calls["n"] == 1


def test_retry_busy_http_does_not_retry_success():
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        return _http_response(200)

    result = _retry_busy_http(send)

    assert result.status_code == 200
    assert calls["n"] == 1


def test_retry_busy_http_retries_stale_timeline_409():
    responses = [
        _http_response(409, {"status": "stale", "message": "advanced"}),
        _http_response(200),
    ]
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        return responses[calls["n"] - 1]

    result = _retry_busy_http(send, sleep=lambda s: None)

    assert result.status_code == 200
    assert calls["n"] == 2


def test_retry_busy_http_does_not_retry_stale_early_exit_409():
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        return _http_response(
            409,
            {
                "status": "error",
                "error_code": "stale_early_exit_offer",
            },
        )

    result = _retry_busy_http(send)

    assert result.status_code == 409
    assert calls["n"] == 1
