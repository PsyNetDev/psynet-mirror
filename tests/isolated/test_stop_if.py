"""Tests for ``stop_if`` on :func:`psynet.timeline.join` and :func:`psynet.timeline.for_loop`."""

import pytest

from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Timeline, for_loop, join

in_timeline_experiment = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)


def _stopped(participant):
    return participant.var.get("stop", False)


def _pages_seen(timeline, participant, monkeypatch, stop_after):
    """Advance through ``timeline``, setting ``stop`` once ``stop_after`` is shown."""
    exp = get_experiment()
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    pages = []
    while not pages or pages[-1] != "After":
        timeline.advance_page(exp, participant)
        pages.append(timeline.get_current_elt(exp, participant).content)
        if pages[-1] == stop_after:
            participant.var.set("stop", True)
    return pages


@in_timeline_experiment
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize(
    "stop_after, expected",
    [
        (None, ["A", "B", "C", "After"]),
        ("A", ["A", "After"]),
        # B and C are one argument, so there is no check between them.
        ("B", ["A", "B", "C", "After"]),
    ],
)
def test_join_stop_if_skips_the_remaining_arguments(
    db_session, participant, monkeypatch, stop_after, expected
):
    timeline = Timeline(
        join(
            InfoPage("A", time_estimate=1),
            join(InfoPage("B", time_estimate=1), InfoPage("C", time_estimate=1)),
            stop_if=_stopped,
        ),
        InfoPage("After", time_estimate=1),
    )
    assert _pages_seen(timeline, participant, monkeypatch, stop_after) == expected


@in_timeline_experiment
@pytest.mark.usefixtures("in_experiment_directory")
def test_for_loop_stop_if_finishes_the_iteration_then_stops(
    db_session, participant, monkeypatch
):
    timeline = Timeline(
        for_loop(
            label="rounds",
            iterate_over=range(3),
            logic=lambda number: join(
                InfoPage(f"Choose {number}", time_estimate=1),
                InfoPage(f"Outcome {number}", time_estimate=1),
            ),
            time_estimate_per_iteration=2,
            stop_if=_stopped,
        ),
        InfoPage("After", time_estimate=1),
    )
    assert _pages_seen(timeline, participant, monkeypatch, "Choose 1") == [
        "Choose 0",
        "Outcome 0",
        "Choose 1",
        "Outcome 1",
        "After",
    ]
