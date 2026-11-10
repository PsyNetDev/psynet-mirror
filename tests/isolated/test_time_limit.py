import sys
from datetime import timedelta
from pathlib import Path

import pytest
from dallinger.models import timenow
from flask import Flask

from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
from psynet.page import InfoPage
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import TIME_LIMIT_GRACE_SECONDS, Response, Timeline

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import (  # noqa: E402
    _json_timeline,
    _working_participants,
)


def _respond(page, participant, raw_answer=None, **metadata):
    return page.process_response(
        raw_answer=raw_answer,
        blobs={},
        metadata=metadata,
        experiment=get_experiment(),
        participant=participant,
    )


def _answer(page, participant, raw_answer=None, **metadata):
    return _respond(page, participant, raw_answer, **metadata).answer


def _submit(exp, participant, raw_answer, **metadata):
    with Flask(__name__).test_request_context("/response"):
        result = exp.process_response(
            participant.id,
            raw_answer,
            {},
            metadata,
            participant.page_uuid,
            "127.0.0.1",
        )
    return result.payload


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_time_limit_counts_from_reaching_the_page(in_experiment_directory, db_session):
    exp = get_experiment()
    (participant,) = _working_participants(exp, 1)
    page = ModularPage(
        "guess", "Guess", TextControl(), time_limit=10, time_limit_answer="timeout"
    )
    page.consume(exp, participant)
    assert 9 < page.time_limit_seconds_left(participant) <= 10

    # A later untimed page has no time limit but keeps the deadline for barriers.
    deadline = participant.page_deadline
    untimed = ModularPage("note", "Note", TextControl())
    untimed.consume(exp, participant)
    assert untimed.time_limit_seconds_left(participant) is None
    assert participant.page_deadline == deadline

    # A rebuilt page, as after a reload, keeps the deadline set on arrival.
    rebuilt = ModularPage("guess", "Guess", TextControl(), time_limit=10)
    participant.page_deadline -= timedelta(seconds=4)
    assert rebuilt.time_limit_seconds_left(participant) <= 6

    assert _answer(page, participant, "7") == "7"
    # The browser's timeout counts only once the deadline is (nearly) reached.
    assert _answer(page, participant, "8", time_limit_reached=True) == "8"
    participant.page_deadline = timenow()
    assert _answer(page, participant, time_limit_reached=True) == "timeout"
    participant.page_deadline = timenow() - timedelta(
        seconds=TIME_LIMIT_GRACE_SECONDS + 1
    )
    assert _answer(page, participant, "late") == "timeout"

    untimed = ModularPage("guess", "Guess", TextControl())
    untimed.consume(exp, participant)
    assert untimed.time_limit_seconds_left(participant) is None
    # The flag skips validation, so a page without a time limit drops it.
    response = _respond(untimed, participant, "7", time_limit_reached=True)
    assert response.answer == "7"
    assert "time_limit_reached" not in response.metadata


def test_time_limit_cannot_share_a_session():
    with pytest.raises(ValueError, match="session_id"):
        ModularPage("guess", "Guess", TextControl(), time_limit=10, session_id="s")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_timeout_answers_skip_validation(in_experiment_directory, db_session):
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        ModularPage(
            "guess",
            "Guess",
            # "timeout" is not a choice, so timeouts also skip the choices check.
            PushButtonControl(["ok", "bad"]),
            time_limit=10,
            time_limit_answer="timeout",
            validate=lambda answer: None if answer == "ok" else "Wrong",
            time_estimate=10,
        ),
        InfoPage("Done", time_estimate=1),
    )
    try:
        (participant,) = _working_participants(exp, 1)
        _json_timeline(exp, participant)

        def submit(raw_answer, **metadata):
            return _submit(exp, participant, raw_answer, **metadata)

        # The browser's countdown ended early: nothing is recorded, and the
        # browser learns how long to wait.
        participant.page_deadline = timenow() + timedelta(seconds=3)
        payload = submit(None, time_limit_reached=True)
        assert payload["submission"] == "rejected"
        assert 2 < payload["time_limit_seconds_left"] <= 3
        assert Response.query.filter_by(participant_id=participant.id).count() == 0

        # Late but within the grace period: validated as usual.
        participant.page_deadline = timenow() - timedelta(seconds=1)
        assert submit("bad")["submission"] == "rejected"

        # Within the tolerance before the deadline, the browser's timeout counts.
        participant.page_deadline = timenow() + timedelta(seconds=1)
        assert submit(None, time_limit_reached=True)["submission"] == "approved"
        (response,) = Response.query.filter_by(
            participant_id=participant.id, successful_validation=True
        )
        assert response.answer == "timeout"
        assert response.metadata["time_limit_reached"] is True
    finally:
        exp.timeline = original


class _BrowserTimeoutAnswerPage(ModularPage):
    """Keeps the browser's answer on time-out, as ``CURRENT_ANSWER`` will."""

    def process_response(self, raw_answer, *args, **kwargs):
        response = super().process_response(raw_answer, *args, **kwargs)
        response.answer = raw_answer
        response._server_time_limit_answer = False
        return response


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_browser_timeout_answers_must_be_choices(in_experiment_directory, db_session):
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        _BrowserTimeoutAnswerPage(
            "guess",
            "Guess",
            PushButtonControl(["ok", "bad"]),
            time_limit=10,
            validate=lambda answer: "Wrong",
            time_estimate=10,
        ),
        InfoPage("Done", time_estimate=1),
    )
    try:
        (participant,) = _working_participants(exp, 1)
        _json_timeline(exp, participant)
        participant.page_deadline = timenow()

        payload = _submit(exp, participant, "tampered", time_limit_reached=True)
        assert payload["submission"] == "rejected"
        # Nothing selected is still accepted, and validate is still skipped.
        payload = _submit(exp, participant, None, time_limit_reached=True)
        assert payload["submission"] == "approved"
    finally:
        exp.timeline = original
