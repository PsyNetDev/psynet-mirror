import sys
from datetime import timedelta
from pathlib import Path

import pytest
from dallinger.models import timenow

from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage, TextControl
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import TIME_LIMIT_GRACE_SECONDS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import _working_participants  # noqa: E402


def _answer(page, participant, raw_answer=None, **metadata):
    response = page.process_response(
        raw_answer=raw_answer,
        blobs={},
        metadata=metadata,
        experiment=get_experiment(),
        participant=participant,
    )
    return response.answer


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

    # A rebuilt page, as after a reload, keeps the deadline set on arrival.
    rebuilt = ModularPage("guess", "Guess", TextControl(), time_limit=10)
    participant.page_deadline -= timedelta(seconds=4)
    assert rebuilt.time_limit_seconds_left(participant) <= 6

    assert _answer(page, participant, "7") == "7"
    assert _answer(page, participant, time_limit_reached=True) == "timeout"
    participant.page_deadline = timenow() - timedelta(
        seconds=TIME_LIMIT_GRACE_SECONDS + 1
    )
    assert _answer(page, participant, "late") == "timeout"

    untimed = ModularPage("guess", "Guess", TextControl())
    untimed.consume(exp, participant)
    assert untimed.time_limit_seconds_left(participant) is None
    assert _answer(untimed, participant, "7", time_limit_reached=True) == "7"
