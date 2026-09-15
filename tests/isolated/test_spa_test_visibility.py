"""SPA contract errors should be visible during local testing."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from psynet.experiment import Experiment
from psynet.modular_page import Control, ModularPage, Prompt
from psynet.participant import (
    _extract_server_error_details,
    _raise_for_status_with_server_details,
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
