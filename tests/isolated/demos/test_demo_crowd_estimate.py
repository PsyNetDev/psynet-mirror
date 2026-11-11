"""Edge cases of the crowd_estimate demo's revision page and median."""

import sys
from types import SimpleNamespace

import pytest

from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.pytest_psynet import path_to_demo_experiment

pytestmark = pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("crowd_estimate")], indirect=True
)


class _Vars(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


def _demo():
    return sys.modules[type(get_experiment()).__module__]


def _trial(participant_id=1, outcome="stayed", estimate=None, timed_out=False):
    return SimpleNamespace(
        participant_id=participant_id,
        sync_group_outcome=outcome,
        sync_group=None,
        answer={"estimate": estimate},
        time_limit_reached=timed_out,
        var=_Vars(),
        question="How many?",
    )


@pytest.mark.parametrize(
    "outcome, median, timed_out, expected",
    [
        ("late", 5, False, "didn't reach your group in time"),
        ("group_dissolved", 5, False, "Your group ended"),
        ("waited_too_long", 5, False, "You left your group"),
        ("removed", None, False, "You left your group"),
        ("stayed", None, False, "Too few estimates"),
        ("stayed", 5, True, "You didn't give an estimate in time"),
        ("stayed", 5, False, "The median of your group's 3 estimates is 5."),
    ],
)
def test_revise_page_explains_each_outcome(
    in_experiment_directory, db_session, outcome, median, timed_out, expected
):
    trial = _trial(outcome=outcome, timed_out=timed_out)
    trial.node = SimpleNamespace(
        var=_Vars(median=median, estimates={"1": 4, "2": 5, "3": 6})
    )
    page = _demo().EstimateTrial.revise_page(trial, participant=None)
    assert isinstance(page, InfoPage) != expected.startswith("The median")
    assert expected in str(page.prompt.text)


def test_score_round_needs_a_quorum_of_estimates_given_in_time(
    in_experiment_directory, db_session
):
    demo = _demo()
    trials = [_trial(i, estimate=e) for i, e in enumerate([10, 20, 31, None])]
    # Removed as late before the release, so not among the released trials.
    late = _trial(4, outcome="late", estimate=99)
    node = SimpleNamespace(var=_Vars(), all_trials=trials + [late])
    demo.EstimateTrial.score_round(trials, node)
    assert (node.var.median, node.var.estimates) == (20, {"0": 10, "1": 20, "2": 31})
    assert [t.var.in_median for t in node.all_trials] == [True] * 3 + [False] * 2

    trials[2].answer["estimate"] = None
    demo.EstimateTrial.score_round(trials, node)
    assert node.var.median is None
    assert [t.var.in_median for t in node.all_trials] == [None] * 5
