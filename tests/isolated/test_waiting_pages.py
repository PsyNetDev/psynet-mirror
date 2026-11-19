import json
import sys
import uuid
from pathlib import Path

import pytest
from dallinger import db
from flask import Flask
from markupsafe import Markup

from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage
from psynet.page import WaitPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import GroupBarrier, SimpleGrouper, waiting_status_payload
from psynet.timeline import (
    CodeBlock,
    PageMaker,
    Response,
    Timeline,
    for_loop,
    join,
    while_loop,
)
from psynet.trial.main import GenericTrialNode, Trial, TrialMaker

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import _json_timeline, _working_participants  # noqa: E402


def _post_response(participant, **fields):
    payload = {
        "participant_id": participant.id,
        "page_uuid": participant.page_uuid,
        "raw_answer": None,
        "metadata": {"time_taken": 1},
        "include_timeline_fragment": False,
        **fields,
    }
    with Flask(__name__).test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment.route_response()


def _filler(label):
    return ModularPage(label, "A filler question", time_estimate=5)


def _use_timeline(exp, waiting_logic, initial_group_size=2, **kwargs):
    exp.timeline = Timeline(
        SimpleGrouper(
            f"pair_{uuid.uuid4().hex[:8]}",
            initial_group_size=initial_group_size,
            waiting_logic=waiting_logic,
            **kwargs,
        ),
        ModularPage("after", "Your partner is here", time_estimate=1),
    )


in_consents_experiment = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)


@pytest.mark.parametrize("n_pages", [1, 2])
@in_consents_experiment
def test_release_interrupts_a_waiting_page(
    in_experiment_directory, db_session, n_pages
):
    """An interrupt only ends the page after release, and skips the pass's other pages."""
    exp = get_experiment()
    original = exp.timeline
    _use_timeline(exp, join(*[_filler(f"filler_{i}") for i in range(n_pages)]))
    try:
        first, last = _working_participants(exp, 2)
        first_id = first.id
        waiting = _json_timeline(exp, first).get_json()["attributes"]["waiting"]
        assert waiting["release_grace_ms"] == 3000
        assert waiting["release_notice"] == (
            "Your group is ready. Moving on in {SECONDS} s."
        )
        assert not waiting_status_payload(first.unique_id, waiting["barrier_id"])[
            "released"
        ]
        last_id = last.id
        early = _post_response(first, interrupted=True).get_json()
        assert early["submission"] == "rejected"

        _json_timeline(exp, Participant.query.get(last_id))
        db.session.expire_all()
        last = Participant.query.get(last_id)
        assert exp.timeline.get_current_elt(exp, last).label == "after"
        first = Participant.query.get(first_id)
        assert waiting_status_payload(first.unique_id, waiting["barrier_id"])[
            "released"
        ]

        _post_response(
            first,
            interrupted=True,
            metadata={"time_taken": 1, "time_limit_reached": True},
        )
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert exp.timeline.get_current_elt(exp, first).label == "after"
        (filler,) = Response.query.filter_by(participant_id=first_id).all()
        assert (filler.question, filler.metadata["interrupted"]) == ("filler_0", True)
        # Only the server may say that a time limit ran out.
        assert "time_limit_reached" not in filler.metadata
    finally:
        exp.timeline = original


def _release_pair(exp):
    """Have two participants arrive; return the first, waiting page config included."""
    first, last = _working_participants(exp, 2)
    first_id, last_id = first.id, last.id
    waiting = _json_timeline(exp, first).get_json()["attributes"]["waiting"]
    _json_timeline(exp, Participant.query.get(last_id))
    db.session.expire_all()
    return Participant.query.get(first_id), waiting


@pytest.mark.parametrize("make_uninterruptible", ["no_release_grace", "failed"])
@in_consents_experiment
def test_release_does_not_end_an_uninterruptible_waiting_page(
    in_experiment_directory, db_session, make_uninterruptible
):
    """Status reports the release without ending the page, and an interrupt is refused."""
    exp = get_experiment()
    original = exp.timeline
    release_grace = None if make_uninterruptible == "no_release_grace" else 3
    _use_timeline(exp, _filler("filler"), release_grace=release_grace)
    try:
        first, waiting = _release_pair(exp)
        if make_uninterruptible == "failed":
            first.failed = True
            db.session.commit()
        status = waiting_status_payload(first.unique_id, waiting["barrier_id"])
        assert (status["released"], status["ends_page"]) == (True, False)
        assert _post_response(first, interrupted=True).get_json()["submission"] == (
            "rejected"
        )
    finally:
        exp.timeline = original


class FillerTrial(Trial):
    time_estimate = 5
    check_time_credit_received = False

    def show_trial(self, experiment, participant):
        return _filler("filler_trial")

    def show_feedback(self, experiment, participant):
        return _filler(f"You said {self.answer['choice']}")


def _start_filler_trial(experiment, participant):
    participant.current_trial = FillerTrial(
        experiment,
        GenericTrialNode("filler", experiment),
        participant,
        propagate_failure=False,
        is_repeat_trial=False,
        definition={},
    )


class _CountingTrialMaker:
    n_finalized = 0

    def with_namespace(self, name):
        return f"counting__{name}"

    def finalize_trial(self, answer, trial, experiment, participant):
        type(self).n_finalized += 1


@in_consents_experiment
def test_a_release_fails_the_unanswered_filler_trials_it_ends(
    in_experiment_directory, db_session
):
    """The first's trial page is interrupted, the last's is skipped.

    The rest of each pass, here a long ``for_loop`` of trials, is walked
    through, so its unseen trials are created and failed too.
    """
    exp = get_experiment()
    original = exp.timeline
    _CountingTrialMaker.n_finalized = 0
    filler = join(
        CodeBlock(_start_filler_trial),
        FillerTrial.trial_logic(trial_maker=_CountingTrialMaker()),
    )
    _use_timeline(exp, for_loop(label="fillers", iterate_over=range(40), logic=filler))
    try:
        first, waiting = _release_pair(exp)
        first_id = first.id
        assert waiting["release_grace_ms"] == 3000
        first.answer = "answer to an earlier page"
        db.session.commit()
        response = _post_response(first, interrupted=True).get_json()
        assert response["submission"] == "approved"
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert exp.timeline.get_current_elt(exp, first).label == "after"
        assert first.for_loops == {}
        trials = FillerTrial.query.all()
        assert len(trials) == 2 * 40
        for trial in trials:
            assert trial.failed_reason == "interrupted_by_release"
            assert trial.complete and not trial.finalized
            assert trial.answer is None
            assert trial not in trial.node.pending_trials
        assert _CountingTrialMaker.n_finalized == 0
        interrupted = Response.query.filter_by(question="filler_trial").one()
        assert interrupted.trial.failed
        assert interrupted.trial.response == interrupted
    finally:
        exp.timeline = original


@in_consents_experiment
def test_a_release_ends_while_loops_inside_the_pass(
    in_experiment_directory, db_session
):
    """A loop ending on completed trials, which the walk never completes, still ends."""
    exp = get_experiment()
    original = exp.timeline
    _CountingTrialMaker.n_finalized = 0
    filler = while_loop(
        "three_completed",
        lambda: _CountingTrialMaker.n_finalized < 3,
        logic=join(
            CodeBlock(_start_filler_trial),
            FillerTrial.trial_logic(trial_maker=_CountingTrialMaker()),
        ),
        expected_repetitions=3,
    )
    _use_timeline(exp, filler)
    try:
        first, _ = _release_pair(exp)
        _post_response(first, interrupted=True)
        db.session.expire_all()
        for participant in Participant.query.all():
            assert exp.timeline.get_current_elt(exp, participant).label == "after"
        for trial in FillerTrial.query.all():
            assert trial.failed_reason == "interrupted_by_release"
            assert trial.complete and not trial.finalized
        assert FillerTrial.query.count() == 2
    finally:
        exp.timeline = original


class _WaitingTrialMaker(_CountingTrialMaker):
    sync_group_type = None
    max_time_waiting_for_trial = 60
    expected_trials_per_participant = 3
    check_performance_every_trial = False
    trial_class = FillerTrial
    _wait_for_trial = TrialMaker._wait_for_trial
    _trial_loop = TrialMaker._trial_loop
    cue_trial = TrialMaker.cue_trial
    trial_available = False

    def _try_to_prepare_trial_solo(self, experiment, participant):
        if self.trial_available:
            _start_filler_trial(experiment, participant)
        participant.trial_status = "available" if self.trial_available else "wait"


@in_consents_experiment
def test_a_release_while_waiting_for_a_trial_skips_the_trial(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original = exp.timeline
    # Drop cue_trial's select_module: this stub trial maker isn't a module.
    _use_timeline(exp, _WaitingTrialMaker().cue_trial()[1:])
    try:
        first, _ = _release_pair(exp)
        assert _post_response(first, interrupted=True).get_json()["submission"] == (
            "approved"
        )
        db.session.expire_all()
        for participant in Participant.query.all():
            assert exp.timeline.get_current_elt(exp, participant).label == "after"
    finally:
        exp.timeline = original


@in_consents_experiment
def test_a_release_fails_the_trial_a_trial_loop_prepared_for_its_next_pass(
    in_experiment_directory, db_session
):
    """The prepared trial isn't left as the current trial at the next barrier."""
    exp = get_experiment()
    original = exp.timeline
    maker = _WaitingTrialMaker()
    maker.trial_available = True
    exp.timeline = Timeline(
        SimpleGrouper(
            f"a_{uuid.uuid4().hex[:8]}",
            initial_group_size=2,
            waiting_logic=maker._trial_loop(),
        ),
        SimpleGrouper(
            f"b_{uuid.uuid4().hex[:8]}",
            initial_group_size=3,
            quorum=3,
            waiting_logic=_filler("filler_b"),
        ),
        ModularPage("after", "Your partner is here", time_estimate=1),
    )
    try:
        first, _ = _release_pair(exp)
        first_id = first.id
        assert _post_response(first, interrupted=True).get_json()["submission"] == (
            "approved"
        )
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert exp.timeline.get_current_elt(exp, first).label == "filler_b"
        trials = FillerTrial.query.all()
        assert len({trial.participant_id for trial in trials}) == 2
        for trial in trials:
            assert trial.failed_reason == "interrupted_by_release"
            assert trial.complete and not trial.finalized
    finally:
        exp.timeline = original


@in_consents_experiment
def test_answering_a_filler_trial_in_the_grace_period_finalizes_it(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original = exp.timeline
    _WaitingTrialMaker.n_finalized = 0
    maker = _WaitingTrialMaker()
    maker.trial_available = True
    _use_timeline(exp, PageMaker(lambda: maker.cue_trial()[1:], time_estimate=5))
    try:
        first, _ = _release_pair(exp)
        first_id = first.id
        answer = _post_response(first, raw_answer={"choice": "yes"}).get_json()
        assert answer["submission"] == "approved"
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert exp.timeline.get_current_elt(exp, first).label == "after"
        (trial,) = FillerTrial.query.filter_by(participant_id=first_id).all()
        assert trial.complete and trial.finalized and not trial.failed
        assert _WaitingTrialMaker.n_finalized == 1
    finally:
        exp.timeline = original


@in_consents_experiment
def test_re_entering_a_barrier_in_its_released_pass_waits_again(
    in_experiment_directory, db_session
):
    """The first passes round 0's barrier, then waits at round 1's."""
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        SimpleGrouper("pair", initial_group_size=2, waiting_logic=_filler("g")),
        for_loop(
            label="rounds",
            iterate_over=range(2),
            logic=GroupBarrier(
                id_="turn", group_type="pair", waiting_logic=_filler("turn_filler")
            ),
        ),
        ModularPage("after", "Your partner is here", time_estimate=1),
    )
    try:
        first, _ = _release_pair(exp)
        first_id = first.id
        _post_response(first, interrupted=True)
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert exp.timeline.get_current_elt(exp, first).label == "turn_filler"
        assert first.for_loops["rounds"]["index"] == 1
    finally:
        exp.timeline = original


@in_consents_experiment
def test_only_waiting_logic_is_refused_inside_a_trial(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (participant,) = _working_participants(exp, 1)
    _start_filler_trial(exp, participant)
    grouper = SimpleGrouper("pair", initial_group_size=2, waiting_logic=_filler("x"))
    with pytest.raises(ValueError, match="waiting_screen"):
        grouper.receive_participant(participant)
    SimpleGrouper("pair", initial_group_size=2).receive_participant(participant)


@in_consents_experiment
def test_waiting_pages_end_on_a_release_earlier_in_the_same_request(
    in_experiment_directory, db_session
):
    """A link released in this session still counts, though ``active_barriers`` keeps it."""
    exp = get_experiment()
    original = exp.timeline
    _use_timeline(exp, join(_filler("filler_0"), _filler("filler_1")))
    try:
        (participant,) = _working_participants(exp, 1)
        _json_timeline(exp, participant)
        page = exp.timeline.get_current_elt(exp, participant)
        participant.active_barriers[page.links["barrier"].id].release()
        assert exp._advance_past_ready_holds(participant, page).label == "after"
    finally:
        exp.timeline = original


@in_consents_experiment
def test_waiting_logic_reused_after_the_barrier_is_shown(
    in_experiment_directory, db_session
):
    """A page maker that resolves the waiting logic again later shows its pages."""
    exp = get_experiment()
    original = exp.timeline
    waiting_logic = PageMaker(lambda: _filler("filler"), time_estimate=5)
    exp.timeline = Timeline(
        SimpleGrouper("pair", initial_group_size=2, waiting_logic=waiting_logic),
        for_loop(label="again", iterate_over=range(1), logic=waiting_logic),
    )
    try:
        first, last = _working_participants(exp, 2)
        _json_timeline(exp, first)
        attributes = _json_timeline(exp, last).get_json()["attributes"]
        assert "waiting" not in attributes
        db.session.expire_all()
        last = Participant.query.get(last.id)
        assert exp.timeline.get_current_elt(exp, last).label == "filler"
    finally:
        exp.timeline = original


@in_consents_experiment
def test_waiting_pages_after_an_inner_barrier_belong_to_the_outer_one(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original = exp.timeline
    inner = SimpleGrouper("inner", initial_group_size=1, waiting_logic=_filler("x"))
    _use_timeline(exp, join(inner, _filler("filler")))
    try:
        first, last = _working_participants(exp, 2)
        waiting = _json_timeline(exp, first).get_json()["attributes"]["waiting"]
        page = exp.timeline.get_current_elt(exp, first)
        assert page.label == "filler"
        assert waiting["barrier_id"] == page.links["barrier"].id
        assert waiting["release_grace_ms"] == 3000

        _json_timeline(exp, last)
        db.session.expire_all()
        last = Participant.query.get(last.id)
        assert exp.timeline.get_current_elt(exp, last).label == "after"
    finally:
        exp.timeline = original


@in_consents_experiment
def test_hold_pages_get_no_waiting_config(in_experiment_directory, db_session):
    exp = get_experiment()
    original = exp.timeline
    _use_timeline(exp, None)
    try:
        (participant,) = _working_participants(exp, 1)
        attributes = _json_timeline(exp, participant).get_json()["attributes"]
        assert "timeline_hold" in attributes and "waiting" not in attributes
    finally:
        exp.timeline = original


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"waiting_logic": _filler("filler"), "release_grace": -1}, "non-negative"),
        ({"release_grace": 5}, "only applies with waiting_logic"),
        ({"below_quorum": lambda participant, group: "fail"}, "Functions aren't"),
    ],
)
def test_grouper_arguments_are_checked(kwargs, message):
    with pytest.raises(ValueError, match=message):
        SimpleGrouper("pair", initial_group_size=2, **kwargs)


def test_wait_page_plain_text_keeps_plain_strings_and_renders_markup():
    assert "<b>x</b>" in WaitPage(1, content="<b>x</b>").plain_text
    assert "<b>" not in WaitPage(1, content=Markup("<b>x</b>")).plain_text
