"""Tests for the crowd_estimate demo's revision page, median and export, with its trials built directly."""

import sys
import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.sync import SimpleSyncGroup
from psynet.timeline import Module, Response

pytestmark = pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("crowd_estimate")], indirect=True
)


def _crowd(n_members):
    """Return the demo module and a group's trials for the first question, in member order."""
    exp = get_experiment()
    demo = sys.modules[type(exp).__module__]
    members = [
        Participant(
            experiment=exp,
            recruiter_id="hotair",
            worker_id=str(uuid.uuid4()),
            hit_id="XYZ",
            assignment_id=str(uuid.uuid4()),
            mode="debug",
        )
        for _ in range(n_members)
    ]
    group = SimpleSyncGroup(
        group_type=demo.GROUP,
        initial_group_size=n_members,
        min_group_size=2,
        n_active_participants=n_members,
        accepts_top_ups=False,
    )
    db.session.add_all([*members, group])
    for participant in members:
        participant.status = "working"
        group.add_participant(participant)
        participant.start_module(Module("game", []))
    db.session.commit()
    for participant in members:
        demo.EstimateTrial.cue({"question": 0}, round=0)[0].consume(exp, participant)
    return demo, [participant.current_trial for participant in members]


@pytest.mark.parametrize(
    "outcome, median, in_median, timed_out, expected",
    [
        ("late", 5, None, False, "didn't reach your group in time"),
        ("group_dissolved", 5, None, False, "Your group ended"),
        ("removed_by_experimenter", 5, None, False, "You were removed from your group"),
        ("stayed", None, None, False, "Too few estimates"),
        ("stayed", 5, False, True, "You didn't give an estimate in time"),
        ("stayed", 5, True, False, "The median of your group's 3 estimates is 5."),
    ],
)
def test_revise_page_explains_each_outcome(
    in_experiment_directory, db_session, outcome, median, in_median, timed_out, expected
):
    _, trials = _crowd(3)
    trial = trials[0]
    trial.sync_group_outcome = outcome
    trial.var.estimate_timed_out = timed_out
    trial.var.in_median = in_median
    trial.node.var.median = median
    trial.node.var.estimates = {
        str(t.participant_id): e for t, e in zip(trials, [4, 5, 6])
    }
    page = trial.revise_page(trial.participant)
    assert isinstance(page, InfoPage) != expected.startswith("The median")
    assert expected in str(page.prompt.text)


def test_score_round_needs_a_quorum_of_estimates_given_in_time(
    in_experiment_directory, db_session
):
    demo, trials = _crowd(5)
    for trial, estimate in zip(trials, [10, 20, 31, None, 99]):
        trial.answer = {"estimate": estimate}
    ids = [str(t.participant_id) for t in trials]
    # The last member was removed as late before the release, so isn't released.
    released, node = trials[:4], trials[0].node
    demo.EstimateTrial.score_round(released, node)
    assert (node.var.median, node.var.estimates) == (20, dict(zip(ids, [10, 20, 31])))
    assert [t.var.in_median for t in trials] == [True] * 3 + [False] * 2

    trials[2].answer = {"estimate": None}
    demo.EstimateTrial.score_round(released, node)
    assert node.var.median is None
    assert [t.var.in_median for t in trials] == [None] * 5


def test_export_says_whether_the_estimate_itself_timed_out(
    in_experiment_directory, db_session
):
    demo, trials = _crowd(3)
    for trial, timed_out in zip(trials, [False, True]):
        response = Response(
            trial.participant,
            "estimate",
            "ModularPage",
            metadata={"time_limit_reached": timed_out},
            trial=trial,
        )
        db.session.add(response)
        db.session.flush()
        trial.save_estimate_timed_out(trial.participant)
        # The revision page, which ran out of time the other way, comes later.
        trial.time_limit_reached = not timed_out
    db.session.commit()

    rows = demo.Exp.get_basic_data()["player_round"]
    # The third member left before answering.
    assert [r["estimate_timed_out"] for r in rows] == [False, True, None]
