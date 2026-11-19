"""Tests for :meth:`Trial.cue` with a trial class that has ``sync_group_type``."""

import logging
import sys
import threading
import time
from pathlib import Path

import pytest
from dallinger import db
from dallinger.models import timenow
from sqlalchemy import text

from psynet.db import _set_transaction_lock_timeout
from psynet.error import ErrorRecord
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage, TextControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    GroupBarrier,
    GroupDivergenceError,
    SimpleGrouper,
    SimpleSyncGroup,
    SyncGroupRound,
    _hold_barrier_instance_claim,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
    check_barriers,
    fail_on_group_divergence,
    leave_group,
)
from psynet.timeline import Module, Timeline, join
from psynet.trial.chain import ChainNode
from psynet.trial.main import (
    GenericTrialNetwork,
    GenericTrialNode,
    Trial,
    _PrepareTrialBarrier,
)
from psynet.trial.static import StaticNode, StaticTrialMaker

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from test_regrouper import _arrive, _cohort_and_pairs  # noqa: E402
from test_sync import (  # noqa: E402
    _arrive_at_group_barrier,
    _set_group_clocks_in_the_past,
    _sync_group_of,
)
from timeline_hold_helpers import (  # noqa: E402
    _json_timeline,
    _process_response,
    _working_participants,
)

in_consents_experiment = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)

_definition_calls = []


def _make_definition(group, round):
    _definition_calls.append((group.id, round))
    return {"target": round}


def _record_definition_args(group, round):
    _definition_calls.append((group, round))
    return {}


class PairTrial(Trial):
    time_estimate = 1
    sync_group_type = "pair"

    def make_definition(self, experiment, participant):
        return {}

    def show_trial(self, experiment, participant):
        raise NotImplementedError

    @classmethod
    def score_pair(cls, trials, group_round):
        group_round.var.players = [trial.participant_id for trial in trials]
        for trial in trials:
            trial.var.scored = True

    @classmethod
    def record_release(cls, participants, trials, group_round):
        _released.append((participants, trials, group_round))


_released = []


def _paired(exp):
    cohort, pairs = _cohort_and_pairs(exp, 2)
    _arrive(exp, pairs, cohort)
    _definition_calls.clear()
    return cohort, pairs


def _pair_role(participant):
    """Return the participant's role in their current pair."""
    group = participant.active_sync_groups["pair"]
    (role,) = [
        link.role
        for link in group.participant_links
        if link.participant_id == participant.id and link.active
    ]
    return role


@in_consents_experiment
def test_a_pair_s_cued_trials_share_one_round_per_round_number(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    cohort, pairs = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    logic = PairTrial.cue(_make_definition)
    for _ in range(2):
        for participant in cohort:
            logic[0].consume(exp, participant)
    db.session.commit()

    trials = PairTrial.query.order_by(PairTrial.id).all()
    roles = [_pair_role(p) for p in cohort]
    assert sorted(roles) == ["proposer", "responder"]
    assert [
        (t.participant_id, t.sync_group_id, t.sync_group_role, t.sync_group_round)
        for t in trials
    ] == [
        (cohort[0].id, pair.id, roles[0], 0),
        (cohort[1].id, pair.id, roles[1], 0),
        (cohort[0].id, pair.id, roles[0], 1),
        (cohort[1].id, pair.id, roles[1], 1),
    ]
    assert [t.definition for t in trials] == [{"target": r} for r in (0, 0, 1, 1)]
    assert _definition_calls == [(pair.id, 0), (pair.id, 1)]
    rounds = [t.group_round for t in trials]
    assert rounds[0] is rounds[1] and rounds[2] is rounds[3]
    assert rounds[0] is not rounds[2]
    assert [r.number for r in rounds] == [0, 0, 1, 1]
    assert rounds[0].trials == trials[:2]
    assert len({t.node_id for t in trials}) == 1
    assert isinstance(trials[0].node, GenericTrialNode)
    PairTrial.cue({"target": 7})[0].consume(exp, cohort[0])
    with pytest.raises(ValueError, match="already has the definition"):
        PairTrial.cue({"target": 8})[0].consume(exp, cohort[1])

    pair.remove_participant(cohort[0], reason="removed_by_experimenter")
    assert trials[0].sync_group is pair
    monkeypatch.setattr(PairTrial, "sync_group_optional", True)
    PairTrial.cue({"target": 9})[0].consume(exp, cohort[0])
    ungrouped = cohort[0].current_trial
    assert ungrouped.sync_group_id is None and ungrouped.group_round is None
    _definition_calls.clear()
    PairTrial.cue(_record_definition_args)[0].consume(exp, cohort[0])
    assert _definition_calls == [(None, None)]


@in_consents_experiment
def test_group_barrier_passes_the_members_trials_to_on_release(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    logic = PairTrial.cue({"target": 3})
    for participant in cohort:
        logic[0].consume(exp, participant)
    db.session.commit()

    barrier = GroupBarrier(
        "pair_done", group_type="pair", on_release=PairTrial.score_pair
    )
    _arrive(exp, barrier, cohort)
    db.session.expire_all()

    trials = PairTrial.query.order_by(PairTrial.participant_id).all()
    assert sorted(trials[0].group_round.var.players) == [p.id for p in cohort]
    assert all(trial.var.scored for trial in trials)


@in_consents_experiment
def test_each_trial_records_how_its_round_ended_for_the_player(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    stayer, leaver = cohort
    pair = stayer.active_sync_groups["pair"]
    for participant in cohort:
        PairTrial.cue(round=0)[0].consume(exp, participant)
    _arrive(exp, GroupBarrier("offered", group_type="pair"), cohort)
    pair.remove_participant(leaver, reason="late")
    _arrive(exp, GroupBarrier("answered", group_type="pair"), [stayer])
    assert [p.current_trial.sync_group_outcome for p in cohort] == ["stayed", "stayed"]

    stayer.current_trial.complete = True
    pair.remove_participant(stayer, reason="finished")
    assert stayer.current_trial.sync_group_outcome == "stayed"
    monkeypatch.setattr(PairTrial, "sync_group_optional", True)
    PairTrial.cue()[0].consume(exp, stayer)
    assert stayer.current_trial.sync_group_outcome is None


@in_consents_experiment
def test_cue_without_a_definition_defaults_to_an_empty_dict(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    PairTrial.cue()[0].consume(exp, cohort[0])
    assert cohort[0].current_trial.definition == {}


@in_consents_experiment
def test_a_waiting_screen_gets_the_trial_and_its_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    PairTrial.cue()[0].consume(exp, cohort[0])
    hold = GroupBarrier(
        "answered", group_type="pair", waiting_screen=_trial_and_round_screen
    ).waiting_logic

    trial = cohort[0].current_trial
    screen = hold.waiting_screen_page(cohort[0])
    assert screen.prompt.text == f"Trial {trial.id} in round {trial.group_round.id}"
    assert hold.waiting_screen_page(cohort[1]).prompt.text == "Trial None in round None"


def _trial_and_round_screen(trial, group_round):
    return f"Trial {getattr(trial, 'id', None)} in round {getattr(group_round, 'id', None)}"


@in_consents_experiment
def test_only_ungrouped_trials_check_their_time_credit(
    in_experiment_directory, db_session, caplog, monkeypatch
):
    exp = get_experiment()
    monkeypatch.setattr(PairTrial, "sync_group_optional", True)
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    PairTrial.cue({})[0].consume(exp, cohort[0])
    pair.remove_participant(cohort[1], reason="removed_by_experimenter")
    PairTrial.cue({})[0].consume(exp, cohort[1])
    with caplog.at_level(logging.INFO):
        for participant in cohort:
            PairTrial._log_time_credit_before_trial(participant)
            participant.inc_time_credit(40)  # e.g. waiting at a barrier
            PairTrial._log_time_credit_after_trial(participant)

    warned = [r.getMessage() for r in caplog.records if "unexpected" in r.getMessage()]
    assert len(warned) == 1 and f"Trial {cohort[1].current_trial.id} " in warned[0]


@in_consents_experiment
def test_a_barrier_release_closes_the_round(in_experiment_directory, db_session):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    logic = PairTrial.cue({"target": 1})
    for participant in cohort:
        logic[0].consume(exp, participant)
    db.session.commit()
    # The first of the round's two barriers (submitted, then revealed)
    # releases, and the trials aren't complete yet.
    _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
    (newcomer,) = _working_participants(exp, 1)
    pair.add_participant(newcomer)
    for participant in [newcomer, *cohort]:
        logic[0].consume(exp, participant)
    db.session.commit()

    assert newcomer.current_trial.sync_group_round == 1
    assert {p.current_trial.group_round for p in cohort} == {
        newcomer.current_trial.group_round
    }


@in_consents_experiment
def test_a_barrier_after_the_trial_waits_for_every_member_and_gets_no_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    for participant in cohort:
        PairTrial.cue({})[0].consume(exp, participant)
        participant.current_trial.complete = True
    (newcomer,) = _working_participants(exp, 1)
    SoloTrial.cue({})[0].consume(exp, newcomer)
    pair.add_participant(newcomer)
    _released.clear()
    barrier = GroupBarrier(
        "feedback", group_type="pair", on_release=PairTrial.record_release
    )
    _arrive(exp, barrier, cohort)
    assert barrier._participant_is_waiting(cohort[0])
    _arrive(exp, barrier, [newcomer])

    ((participants, trials, group_round),) = _released
    assert group_round is None
    assert {p.id: t for p, t in zip(participants, trials)} == {
        p.id: p.current_trial for p in [*cohort, newcomer]
    }
    assert cohort[0].current_trial.group_round.closed_at is None
    assert [p.current_trial.sync_group_outcome for p in cohort] == [None, None]


@in_consents_experiment
def test_a_release_waits_for_a_member_still_cueing_the_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    (late_cuer,) = _working_participants(exp, 1)
    pair.add_participant(late_cuer)
    db.session.commit()
    logic = PairTrial.cue({"target": 1})
    for participant in cohort:
        logic[0].consume(exp, participant)
    db.session.commit()
    barrier = GroupBarrier("submitted", group_type="pair")
    cued, checked, errors = threading.Event(), threading.Event(), []

    def cue_slowly():
        try:
            logic[0].consume(exp, db.session.get(Participant, late_cuer.id))
            cued.set()
            assert checked.wait(timeout=10)
            db.session.commit()
        except Exception as err:  # noqa: BLE001 - reported by the assertion below
            errors.append(err)
        finally:
            db.session.remove()

    cue_request = threading.Thread(target=cue_slowly)
    cue_request.start()
    assert cued.wait(timeout=10)
    # Without a round lock, the barrier still waits for the member cueing it.
    assert barrier.choose_who_to_release(cohort) == []
    checked.set()
    cue_request.join(timeout=10)
    assert errors == []
    db.session.expire_all()
    late_cuer = db.session.get(Participant, late_cuer.id)
    group_round = cohort[0].current_trial.group_round
    assert late_cuer.current_trial.group_round is group_round
    _arrive(exp, barrier, [*cohort, late_cuer])
    assert group_round.closed_at is not None


def _cue_in_parallel(exp, logic, participants):
    """Cue for two participants in parallel requests, the first committing a second late."""
    ids = [participant.id for participant in participants]
    first_cued = threading.Event()
    errors = []

    def cue(participant_id, delay_commit):
        try:
            logic[0].consume(exp, db.session.get(Participant, participant_id))
            first_cued.set()
            time.sleep(delay_commit)
            db.session.commit()
        except Exception as err:  # noqa: BLE001 - reported by the assertion below
            errors.append(err)
        finally:
            db.session.remove()

    first = threading.Thread(target=cue, args=(ids[0], 1.0))
    first.start()
    assert first_cued.wait(timeout=10)
    second = threading.Thread(target=cue, args=(ids[1], 0))
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert errors == []
    db.session.expire_all()


@in_consents_experiment
def test_members_cueing_in_parallel_get_one_round(in_experiment_directory, db_session):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    _cue_in_parallel(exp, PairTrial.cue(_make_definition), cohort)

    group_round = SyncGroupRound.query.one()
    assert {t.sync_group_round_id for t in PairTrial.query} == {group_round.id}
    assert group_round.definition == {"target": 0}
    assert len(_definition_calls) == 1


class SoloTrial(Trial):
    time_estimate = 1

    def show_trial(self, experiment, participant):
        raise NotImplementedError

    @classmethod
    def record_round(cls, group_round):
        _released_rounds.append(group_round)


_released_rounds = []


@in_consents_experiment
def test_first_ungrouped_trials_cued_in_parallel_share_the_default_node(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    _cue_in_parallel(exp, SoloTrial.cue({"target": 1}), cohort)

    assert len({t.node_id for t in SoloTrial.query}) == 1
    assert GenericTrialNetwork.query.count() == 1


def test_cue_takes_round_only_when_the_trial_has_a_sync_group_type():
    with pytest.raises(ValueError, match="takes round="):
        SoloTrial.cue({}, round=0)
    for bad in (-1, 1.0, True, "1"):
        with pytest.raises(ValueError, match="non-negative integer"):
            PairTrial.cue({}, round=bad)


def test_a_grouped_cue_takes_no_node():
    with pytest.raises(TypeError, match="pass a dict or a function"):
        PairTrial.cue(ChainNode.__new__(ChainNode))


def test_a_trial_maker_rejects_a_trial_class_of_another_group_type():
    with pytest.raises(ValueError, match="only Trial.cue uses"):
        StaticTrialMaker(
            id_="mismatch",
            trial_class=PairTrial,
            nodes=[StaticNode(definition={})],
            expected_trials_per_participant=1,
            sync_group_type="room",
        )


@in_consents_experiment
def test_each_module_numbers_a_group_s_rounds_from_0(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for module_id in ("practice", "main"):
        for participant in cohort:
            participant.start_module(Module(module_id, InfoPage("Hi", time_estimate=1)))
            PairTrial.cue({"target": 1})[0].consume(exp, participant)
    db.session.commit()

    assert sorted((r.module_id, r.number) for r in SyncGroupRound.query) == [
        ("main", 0),
        ("practice", 0),
    ]


@in_consents_experiment
def test_a_group_lists_its_rounds_of_a_module_in_order_after_it_ends(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    for participant in cohort:
        participant.start_module(Module("story", InfoPage("Hi", time_estimate=1)))
    for i in [1, 0]:
        for participant in cohort:
            PairTrial.cue({"target": i}, round=i)[0].consume(exp, participant)
    for participant in cohort:
        pair.remove_participant(participant, reason="finished")

    assert not pair.active
    assert [r.definition["target"] for r in pair.rounds("story")] == [0, 1]
    assert pair.rounds("other") == []


@in_consents_experiment
def test_module_states_count_the_participant_s_runs_of_the_module(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (participant,) = _working_participants(exp, 1)
    looped = Module("looped", InfoPage("Hi", time_estimate=1))
    for _ in range(2):
        participant.start_module(looped)
        participant.end_module(looped)
    participant.start_module(Module("other", InfoPage("Hi", time_estimate=1)))

    assert [s.run_index for s in participant.module_states["looped"]] == [1, 2]
    assert participant.module_state.run_index == 1


@in_consents_experiment
def test_a_barrier_before_a_module_s_first_cue_gets_no_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for participant in cohort:
        participant.start_module(Module("first", InfoPage("Hi", time_estimate=1)))
        PairTrial.cue({})[0].consume(exp, participant)
    first_trials = [p.current_trial for p in cohort]
    for participant in cohort:
        participant.start_module(Module("second", InfoPage("Hi", time_estimate=1)))
    _released.clear()
    barrier = GroupBarrier(
        "second_start", group_type="pair", on_release=PairTrial.record_release
    )
    _arrive(exp, barrier, cohort)

    ((participants, trials, group_round),) = _released
    assert group_round is None
    assert {p.id: t for p, t in zip(participants, trials)} == {
        t.participant_id: t for t in first_trials
    }
    assert [t.sync_group_outcome for t in first_trials] == [None, None]
    assert first_trials[0].group_round.closed_at is None
    # Leaving the group in a later module doesn't record on the earlier round.
    cohort[1].fail("questionnaire attention check")
    assert [t.sync_group_outcome for t in first_trials] == [None, None]


def _start_a_second_run(exp, restarting=2):
    """Play a round of module ``game``, then start ``game`` again, as in a loop around it.

    Only the first ``restarting`` members start the second run.
    """
    cohort, _ = _paired(exp)
    game = Module("game", InfoPage("Hi", time_estimate=1))
    for participant in cohort:
        participant.start_module(game)
        PairTrial.cue({})[0].consume(exp, participant)
    for participant in cohort[:restarting]:
        participant.end_module(game)
        participant.start_module(game)
    return cohort, [p.current_trial for p in cohort]


@in_consents_experiment
def test_a_barrier_before_a_later_run_s_first_cue_gets_no_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, first_trials = _start_a_second_run(exp)
    _released.clear()
    barrier = GroupBarrier(
        "second_run_start", group_type="pair", on_release=PairTrial.record_release
    )
    _arrive(exp, barrier, cohort)

    ((_, _, group_round),) = _released
    assert group_round is None
    assert [t.sync_group_outcome for t in first_trials] == [None, None]
    assert first_trials[0].group_round.closed_at is None


@in_consents_experiment
def test_a_barrier_before_a_later_run_s_first_cue_waits_for_a_partner_still_in_the_earlier_run(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _start_a_second_run(exp, restarting=1)
    barrier = GroupBarrier("second_run_start", group_type="pair")
    _arrive(exp, barrier, cohort[:1])
    assert barrier._participant_is_waiting(cohort[0])

    game = Module("game", InfoPage("Hi", time_estimate=1))
    cohort[1].end_module(game)
    cohort[1].start_module(game)
    _arrive(exp, barrier, cohort[1:])
    assert not any(barrier._participant_is_waiting(p) for p in cohort)


@pytest.mark.parametrize("round_closed", [False, True])
@in_consents_experiment
def test_a_newcomer_starts_a_later_run_with_the_group(
    in_experiment_directory, db_session, round_closed
):
    exp = get_experiment()
    cohort, trials = _start_a_second_run(exp)
    trials[0].group_round.closed_at = timenow() if round_closed else None
    (newcomer,) = _working_participants(exp, 1)
    cohort[0].active_sync_groups["pair"].add_participant(newcomer)
    newcomer.start_module(Module("game", InfoPage("Hi", time_estimate=1)))
    _released.clear()
    barrier = GroupBarrier(
        "second_run_start", group_type="pair", on_release=PairTrial.record_release
    )
    _arrive(exp, barrier, [newcomer])
    assert barrier._participant_is_waiting(newcomer)
    _arrive(exp, barrier, cohort)

    ((participants, _, _),) = _released
    assert {p.id for p in participants} == {p.id for p in [*cohort, newcomer]}


@in_consents_experiment
def test_a_run_s_start_waits_for_a_member_with_fewer_earlier_runs_of_the_module(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    game = Module("game", InfoPage("Hi", time_estimate=1))
    practiced, new = cohort
    practiced.start_module(game)
    PairTrial.cue({})[0].consume(exp, practiced)
    practiced.end_module(game)
    for participant in cohort:
        participant.start_module(game)
    barrier = GroupBarrier("start", group_type="pair")
    _arrive(exp, barrier, [practiced])
    assert barrier._participant_is_waiting(practiced)
    _arrive(exp, barrier, [new])
    assert not any(barrier._participant_is_waiting(p) for p in cohort)


@in_consents_experiment
def test_a_run_s_start_releases_members_with_different_earlier_runs_together(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _start_a_second_run(exp, restarting=1)
    ahead, behind = cohort
    game = Module("game", InfoPage("Hi", time_estimate=1))
    PairTrial.cue({})[0].consume(exp, ahead)
    ahead.end_module(game)
    ahead.start_module(game)
    behind.end_module(game)
    behind.start_module(game)
    barrier = GroupBarrier("run_start", group_type="pair")
    _arrive(exp, barrier, [ahead])
    assert barrier._participant_is_waiting(ahead)
    _arrive(exp, barrier, [behind])
    assert not any(barrier._participant_is_waiting(p) for p in cohort)


@in_consents_experiment
def test_leaving_in_a_later_run_does_not_record_on_the_earlier_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, first_trials = _start_a_second_run(exp)
    cohort[1].fail("questionnaire attention check")
    assert [t.sync_group_outcome for t in first_trials] == [None, None]


class VoteTrial(Trial):
    time_estimate = 1
    sync_group_type = "pair"

    def show_trial(self, experiment, participant):
        return InfoPage("Vote", time_estimate=1)


@in_consents_experiment
def test_a_grouped_cued_trial_needs_a_group_barrier(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    VoteTrial.cue({})[0].consume(exp, cohort[0])
    with pytest.raises(ValueError, match="needs a GroupBarrier to close each round"):
        cohort[0].current_trial._show_trial(exp, cohort[0])


class LateVoteTrial(VoteTrial):
    def show_trial(self, experiment, participant):
        return GroupBarrier(
            "voted", group_type="pair", late_after=30, late_action="leave_group"
        )


@in_consents_experiment
def test_a_cued_trial_s_leave_group_barrier_needs_a_group_that_survives_it(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    LateVoteTrial.cue({})[0].consume(exp, cohort[0])
    cohort[0].active_sync_groups["pair"].below_quorum = "fail"
    with pytest.raises(ValueError, match="carry on alone"):
        cohort[0].current_trial._show_trial(exp, cohort[0])
    cohort[0].active_sync_groups["pair"].below_quorum = "continue_without_group"
    cohort[0].current_trial._show_trial(exp, cohort[0])
    # A group still taking newcomers could wait for them forever.
    cohort[0].active_sync_groups["pair"].accepts_top_ups = True
    with pytest.raises(ValueError, match="Pass top_up_wait"):
        cohort[0].current_trial._show_trial(exp, cohort[0])
    cohort[0].active_sync_groups["pair"].top_up_wait = 30
    cohort[0].current_trial._show_trial(exp, cohort[0])


@in_consents_experiment
def test_alternating_trial_classes_advance_the_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for trial_class in (PairTrial, VoteTrial):
        for participant in cohort:
            trial_class.cue({"target": 1})[0].consume(exp, participant)
    db.session.commit()

    assert sorted((type(t).__name__, t.sync_group_round) for t in Trial.query) == [
        ("PairTrial", 0),
        ("PairTrial", 0),
        ("VoteTrial", 1),
        ("VoteTrial", 1),
    ]

    # Different classes cued by different players in an open round share it.
    PairTrial.cue({"target": 1})[0].consume(exp, cohort[0])
    VoteTrial.cue({"target": 1})[0].consume(exp, cohort[1])
    assert cohort[0].current_trial.group_round is cohort[1].current_trial.group_round


@in_consents_experiment
def test_an_explicit_round_lets_two_classes_share_a_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for participant in cohort:
        PairTrial.cue(lambda: {"target": 1}, round=4)[0].consume(exp, participant)
    db.session.commit()
    # The first class's barrier releases, but round= still joins the round.
    _arrive(exp, GroupBarrier("offered", group_type="pair"), cohort)
    with pytest.raises(ValueError, match="already has the definition"):
        VoteTrial.cue({"target": 2}, round=4)[0].consume(exp, cohort[1])
    for participant in cohort:
        VoteTrial.cue({"target": 1}, round=4)[0].consume(exp, participant)
    PairTrial.cue({"target": 1})[0].consume(exp, cohort[0])
    db.session.commit()

    assert [t.sync_group_round for t in Trial.query.order_by(Trial.id)] == [
        4,
        4,
        4,
        4,
        5,
    ]
    assert SyncGroupRound.query.count() == 2


@in_consents_experiment
def test_cues_need_an_admitted_member_of_an_open_round(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    (newcomer,) = _working_participants(exp, 1)
    for participant in cohort:
        _cue_round(exp, participant, 0)
    _arrive(exp, GroupBarrier("answered", group_type="pair"), cohort)
    pair.add_participant(newcomer)
    with pytest.raises(RuntimeError, match="finished without them"):
        _cue_round(exp, newcomer, 0)
    assert _cue_round(exp, newcomer, 1).group_round.number == 1

    pending = pair._active_link(newcomer)
    pending.admitted_at = None
    with pytest.raises(RuntimeError, match="before an admission point"):
        PairTrial.cue()[0].consume(exp, newcomer)

    pair.remove_participant(cohort[1], reason="removed_by_experimenter")
    with pytest.raises(RuntimeError, match="sync_group_optional"):
        _cue_round(exp, cohort[1], 2)
    monkeypatch.setattr(PairTrial, "sync_group_optional", True)
    alone = _cue_round(exp, cohort[1], 2)
    assert alone.sync_group_id is None and alone.definition == {"target": 2}


def _cue_round(exp, participant, i):
    PairTrial.cue({"target": i}, round=i)[0].consume(exp, participant)
    return participant.current_trial


def _complete_trials(participants):
    for participant in participants:
        participant.current_trial.complete = True


@pytest.mark.parametrize("cued_before", [False, True])
@in_consents_experiment
def test_a_barrier_outside_cued_rounds_waits_for_every_member(
    in_experiment_directory, db_session, cued_before
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    if cued_before:
        game = Module("game", InfoPage("Hi", time_estimate=1))
        for participant in cohort:
            participant.start_module(game)
            _cue_round(exp, participant, 0)
            participant.end_module(game)
    survey = Module("survey", InfoPage("Bye", time_estimate=1))
    for participant in cohort:
        participant.start_module(survey)

    barrier = GroupBarrier("survey_sync", group_type="pair")
    _arrive(exp, barrier, cohort[:1])
    assert barrier._participant_is_waiting(cohort[0])
    _arrive(exp, barrier, cohort[1:])
    assert not any(barrier._participant_is_waiting(p) for p in cohort)


@in_consents_experiment
def test_rounds_named_out_of_order_release_their_barriers(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for i in [1, 0]:
        for participant in cohort:
            PairTrial.cue({"target": i}, round=i)[0].consume(exp, participant)
        barrier = GroupBarrier(
            f"answered_{i}", group_type="pair", on_release=PairTrial.score_pair
        )
        _arrive(exp, barrier, cohort)
        assert not any(barrier._participant_is_waiting(p) for p in cohort)
        group_round = cohort[0].current_trial.group_round
        assert group_round.number == i
        assert sorted(group_round.var.players) == [p.id for p in cohort]


def _newcomer_in_round_0(exp, round_closed=False):
    """Pair a cohort in round 0 of module ``rounds``, then add a newcomer starting the module."""
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    module = Module("rounds", InfoPage("Hi", time_estimate=1))
    for participant in cohort:
        participant.start_module(module)
        _cue_round(exp, participant, 0)
    if round_closed:
        _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
    (newcomer,) = _working_participants(exp, 1)
    pair.add_participant(newcomer)
    newcomer.start_module(module)
    return cohort, newcomer, pair


@in_consents_experiment
def test_a_barrier_after_the_pages_between_runs_waits_for_the_slow_member(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    game = Module("game", InfoPage("Hi", time_estimate=1))
    for participant in cohort:
        participant.start_module(game)
        participant.end_module(game)
    fast, slow = cohort
    ready = GroupBarrier("ready", group_type="pair")
    # The slow member is still on the page between runs, not yet at "ready".
    _arrive(exp, ready, [fast])
    assert ready._participant_is_waiting(fast)
    _arrive(exp, ready, [slow])
    assert not any(ready._participant_is_waiting(p) for p in cohort)


@in_consents_experiment
def test_late_after_in_a_round_fails_a_newcomer_waiting_outside_it(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, newcomer, pair = _newcomer_in_round_0(exp)
    late = dict(group_type="pair", late_after=5, late_action="fail")
    in_round = GroupBarrier("submitted", **late)
    _arrive(exp, in_round, cohort[:1])
    _arrive(exp, GroupBarrier("ready", **late), [newcomer])
    _set_group_clocks_in_the_past(pair, seconds=10)
    in_round.check_waiting_participants(cohort[:1])
    # The round waits for the newcomer, who isn't at its barrier.
    assert cohort[1].failed and newcomer.failed


def divergences():
    """Sweep the barriers, as the poller does, and return the divergences recorded."""
    db.session.commit()
    check_barriers()
    return [r.message for r in ErrorRecord.query.filter_by(kind="GroupDivergenceError")]


def _in_round(**kwargs):
    return GroupBarrier("submitted", group_type="pair", **kwargs)


def _arrives(exp, pair, cohort):
    _arrive(exp, _in_round(), cohort)


def _arrives_as_the_poller_holds_the_visit(exp, pair, cohort):
    _arrive(exp, _in_round(), cohort[:1])
    _arrive_at_group_barrier(exp, _in_round(), cohort[1])
    db.session.commit()
    checks = _take_pending_barrier_checks()
    with _hold_barrier_instance_claim(checks[0]) as claimed:
        assert claimed and not _run_pending_barrier_checks(checks, wait=False)


def _leaves(exp, pair, cohort):
    _arrive(exp, _in_round(), cohort[:1])
    leave_group("pair").consume(exp, cohort[1])


def _is_removed_as_late(exp, pair, cohort):
    _arrive(exp, _in_round(late_after=5, late_action="leave_group"), cohort[:1])
    newcomer_link = max(pair.participant_links, key=lambda link: link.arrival_time)
    joined = newcomer_link.admitted_at
    _set_group_clocks_in_the_past(pair, seconds=10)
    newcomer_link.admitted_at = joined


@pytest.mark.parametrize(
    "second_member",
    [_arrives, _arrives_as_the_poller_holds_the_visit, _leaves, _is_removed_as_late],
)
@in_consents_experiment
def test_a_sweep_reports_members_waiting_for_each_other_at_different_barriers(
    in_experiment_directory, db_session, caplog, second_member
):
    exp = get_experiment()
    cohort, newcomer, pair = _newcomer_in_round_0(exp)
    # A barrier at the start of each iteration, which the newcomer reaches first.
    _arrive(exp, GroupBarrier("ready", group_type="pair"), [newcomer])
    second_member(exp, pair, cohort)
    # A record of a divergence at other barriers doesn't hide this one.
    db.session.add(
        ErrorRecord(RuntimeError("Earlier"), token=f"group-divergence-{pair.id}:ready")
    )
    with caplog.at_level(logging.ERROR):
        (message,) = divergences()
    assert f"'ready' has participants {newcomer.id}" in message
    assert f"'submitted' has participants {cohort[0].id}" in message
    assert message in [r.getMessage() for r in caplog.records]
    assert _in_round()._participant_is_waiting(cohort[0])
    assert divergences() == [message]
    (record,) = ErrorRecord.query.filter_by(kind="GroupDivergenceError")
    assert record.token == f"group-divergence-{pair.id}:ready,submitted"
    assert record.participant_id == min(newcomer.id, cohort[0].id)


@in_consents_experiment
def test_bot_tests_fail_with_a_divergence_recorded_while_they_run(
    in_experiment_directory, db_session
):
    db.session.add(ErrorRecord(GroupDivergenceError("From an earlier run.")))
    db.session.commit()
    with pytest.raises(GroupDivergenceError, match="^Recorded during the run.$"):
        with fail_on_group_divergence():
            db.session.add(
                ErrorRecord(GroupDivergenceError("Recorded during the run."))
            )
            db.session.commit()
            raise RuntimeError("A bot timed out at its barrier.")


def _at_a_regrouper_and_a_barrier(exp):
    cohort, pairs = _cohort_and_pairs(exp, 2)
    _arrive(exp, pairs, cohort[:1])
    _arrive(exp, GroupBarrier("ready", group_type="cohort"), cohort[1:])


def _everyone_at_one_barrier(exp):
    cohort, newcomer, _ = _newcomer_in_round_0(exp)
    _arrive(exp, _in_round(), [*cohort, newcomer])


@pytest.mark.parametrize(
    "arrange",
    [
        _at_a_regrouper_and_a_barrier,
        _everyone_at_one_barrier,
    ],
)
@in_consents_experiment
def test_a_sweep_does_not_report_a_group_that_can_pass(
    in_experiment_directory, db_session, arrange
):
    arrange(get_experiment())
    assert divergences() == []


@in_consents_experiment
def test_a_member_who_ended_the_loop_without_leaving_is_waited_for(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    game = Module("game", InfoPage("Hi", time_estimate=1))
    for participant in cohort:
        participant.start_module(game)
    stopped, playing = cohort
    # ``stopped`` is on a page after the loop, still in the group.
    stopped.end_module(game)
    ready = GroupBarrier("ready", group_type="pair")
    _arrive(exp, ready, [playing])
    assert ready._participant_is_waiting(playing)


@in_consents_experiment
def test_a_barrier_repeated_in_a_round_waits_for_everyone_each_time(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for participant in cohort:
        _cue_round(exp, participant, 0)
    step = GroupBarrier("step", group_type="pair")
    _arrive(exp, step, cohort)
    _arrive(exp, step, cohort[:1])
    assert step._participant_is_waiting(cohort[0])


@pytest.mark.parametrize(
    "module_ids, n_rounds",
    [(["a"], 1), (["a"], 2), (["a", "b", "a"], 0)],
)
@in_consents_experiment
def test_cueing_a_played_round_again_raises(
    in_experiment_directory, db_session, module_ids, n_rounds
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    *earlier_ids, module_id = module_ids
    for earlier_id in earlier_ids:
        earlier = Module(earlier_id, InfoPage("Hi", time_estimate=1))
        for participant in cohort:
            participant.start_module(earlier)
            _cue_round(exp, participant, 0)
        _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
        _complete_trials(cohort)
        for participant in cohort:
            participant.end_module(earlier)
    module = Module(module_id, InfoPage("Hi", time_estimate=1))
    for participant in cohort:
        participant.start_module(module)
    for i in range(n_rounds):
        for participant in cohort:
            _cue_round(exp, participant, i)
        _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
    with pytest.raises(RuntimeError, match="again"):
        _cue_round(exp, cohort[-1], 0)


@in_consents_experiment
def test_a_late_joiner_joins_an_open_round_or_starts_the_next(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    early, between = _working_participants(exp, 2)
    logic = PairTrial.cue({"target": 1})
    for participant in cohort:
        logic[0].consume(exp, participant)
    pair.add_participant(early)
    logic[0].consume(exp, early)
    # Round 0 closes when its barrier releases the group.
    _arrive(exp, GroupBarrier("submitted", group_type="pair"), [*cohort, early])
    pair.add_participant(between)
    for participant in [between, *cohort]:
        logic[0].consume(exp, participant)
    db.session.commit()

    rounds = {t.participant_id: [] for t in PairTrial.query}
    for t in PairTrial.query.order_by(PairTrial.id):
        rounds[t.participant_id].append(t.sync_group_round)
    assert rounds == {
        cohort[0].id: [0, 1],
        cohort[1].id: [0, 1],
        early.id: [0],
        between.id: [1],
    }
    assert SyncGroupRound.query.count() == 2


@in_consents_experiment
def test_on_release_gets_no_round_for_ungrouped_trials(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    logic = SoloTrial.cue({"target": 1})
    for participant in cohort:
        logic[0].consume(exp, participant)
    db.session.commit()
    _released_rounds.clear()

    barrier = GroupBarrier(
        "solo_done", group_type="pair", on_release=SoloTrial.record_round
    )
    _arrive(exp, barrier, cohort)
    assert _released_rounds == [None]


class CustomStaticTrialMaker(StaticTrialMaker):
    """Prepares the leader's trials itself, as trial makers that override prepare_trial do."""

    def prepare_trial(self, experiment, participant):
        node = Trial.get_default_parent_node(participant, experiment)
        trial = PairTrial(experiment, node, participant, False, False, definition={})
        self._finalize_created_trial(trial)
        return trial, "available"


def _paired_trial_maker(exp):
    """Return a pair, its members (leader first) and a trial maker they have started."""
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    return pair, [pair.leader, *pair.active_followers], _started_trial_maker(cohort)


def _started_trial_maker(participants):
    trial_maker = CustomStaticTrialMaker(
        id_="paired_static",
        trial_class=PairTrial,
        nodes=[StaticNode(definition={})],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        sync_group_type="pair",
    )
    for participant in participants:
        participant.start_module(trial_maker)
        participant.module_state.trial_maker_initialized = True
    return trial_maker


@in_consents_experiment
def test_a_trial_maker_s_next_trials_close_its_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    pair, members, trial_maker = _paired_trial_maker(exp)
    trial_maker._try_to_prepare_trial_group(pair, members)
    first = members[0].current_trial.group_round
    assert (first.module_id, first.trial_maker_id) == (trial_maker.id,) * 2
    assert set(first.trials) == {p.current_trial for p in members}

    _complete_trials(members)
    trial_maker._try_to_prepare_trial_group(pair, members)
    second = members[0].current_trial.group_round
    assert first.closed_at is not None and second.closed_at is None
    assert [t.sync_group_outcome for t in first.trials] == ["stayed", "stayed"]
    assert pair.rounds(trial_maker.id) == [first, second]


@in_consents_experiment
def test_preparing_trials_admits_pending_members_to_the_new_round(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "pair",
        initial_group_size=2,
        max_group_size=3,
        quorum=2,
        target_group_size=2,
        join_existing_groups=True,
        use_admission_points=True,
        top_up_wait=30,
        below_quorum="continue_without_group",
    )
    founders = _working_participants(exp, 2)
    pair = grouper._make_group(founders, initial_group_size=2)
    (newcomer,) = _working_participants(exp, 1)
    grouper._join_existing_groups(newcomer)
    db_session.commit()
    trial_maker = CustomStaticTrialMaker(
        id_="paired_static",
        trial_class=PairTrial,
        nodes=[StaticNode(definition={})],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        sync_group_type="pair",
        sync_group_newcomer_max_wait=60,
    )
    monkeypatch.setitem(exp.timeline.trial_makers, trial_maker.id, trial_maker)
    trial_maker.pre_deploy_routine(exp)
    members = [*founders, newcomer]
    for participant in members:
        participant.start_module(trial_maker)
    _arrive(exp, _PrepareTrialBarrier(trial_maker), members)
    assert pair.active_participants == members
    (group_round,) = {p.current_trial.group_round for p in members}
    assert set(group_round.trials) == {p.current_trial for p in members}


@in_consents_experiment
def test_a_barrier_in_a_trial_maker_s_trial_closes_its_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    pair, members, trial_maker = _paired_trial_maker(exp)
    trial_maker._try_to_prepare_trial_group(pair, members)
    group_round = members[0].current_trial.group_round
    _arrive(exp, GroupBarrier("answered", group_type="pair"), members)
    assert group_round.closed_at is not None
    assert [t.sync_group_outcome for t in group_round.trials] == ["stayed"] * 2


@in_consents_experiment
def test_a_trial_maker_s_round_records_its_group_dissolving(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (stayer, leaver), pair = _sync_group_of(exp, db_session, 2, group_type="pair")
    pair.below_quorum = "continue_without_group"
    trial_maker = _started_trial_maker([stayer, leaver])
    trial_maker._try_to_prepare_trial_group(pair, [stayer, leaver])
    db.session.commit()
    group_round = stayer.current_trial.group_round
    leaver.fail("returned")
    assert group_round.dissolved_at is not None and group_round.closed_at is None
    assert stayer.current_trial.sync_group_outcome == "group_dissolved"
    assert leaver.current_trial.sync_group_outcome == "left_experiment"


@in_consents_experiment
def test_a_synchronized_trial_maker_records_group_role_and_round(
    in_experiment_directory, db_session, caplog
):
    exp = get_experiment()
    pair, members, trial_maker = _paired_trial_maker(exp)
    for round in (0, 1, 2):
        if round == 2:
            # Repeat each player's last trial.
            for p in members:
                state = p.module_state
                state.in_repeat_phase = True
                state.trials_to_repeat = [p.current_trial.id]
                state.repeat_trial_index = 0
        trial_maker._try_to_prepare_trial_group(pair, members)
        db.session.flush()
        assert [
            (
                p.current_trial.sync_group_id,
                p.current_trial.sync_group_role,
                p.current_trial.sync_group_round,
            )
            for p in members
        ] == [(pair.id, _pair_role(p), round) for p in members]
    assert all(p.current_trial.is_repeat_trial for p in members)

    with caplog.at_level(logging.INFO):
        for participant in members:
            PairTrial._log_time_credit_before_trial(participant)
            participant.inc_time_credit(40)  # e.g. waiting at a barrier
            PairTrial._log_time_credit_after_trial(participant)
    assert "unexpected amount of time credit" not in caplog.text


class TeamTrial(Trial):
    time_estimate = 1
    sync_group_type = "main"


class EstimateTrial(Trial):
    time_estimate = 1
    sync_group_type = "main"
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        return join(
            ModularPage("estimate", "Estimate", TextControl(), time_estimate=1),
            GroupBarrier("submitted", group_type="main"),
            ModularPage("revise", "Revise", TextControl(), time_estimate=1),
        )


def _submit(exp, participant, raw_answer):
    _process_response(exp, participant, participant.page_uuid, raw_answer=raw_answer)
    db.session.commit()


@in_consents_experiment
def test_a_dissolved_round_keeps_its_answers_and_outcomes(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (waiter, reader, quitter), group = _sync_group_of(exp, db_session, 3)
    group.below_quorum = "continue_without_group"
    original = exp.timeline
    exp.timeline = Timeline(*EstimateTrial.cue({}), InfoPage("Done", time_estimate=1))
    try:
        for participant in (waiter, reader, quitter):
            _json_timeline(exp, participant)
        _submit(exp, waiter, "5")
        quitter.fail("returned")
        db.session.commit()
        # The reader was on the estimate page; the revision doesn't replace it.
        _submit(exp, reader, "3")
        _submit(exp, reader, "4")
    finally:
        exp.timeline = original

    assert {
        (t.participant_id, t.answer.get("estimate"), t.sync_group_outcome)
        for t in waiter.current_trial.group_round.trials
    } == {
        (waiter.id, "5", "group_dissolved"),
        (reader.id, "3", "group_dissolved"),
        (quitter.id, None, "left_experiment"),
    }
    assert reader.current_trial.answer == {"estimate": "3", "revise": "4"}


def _late_at_barrier(late_action):
    def remove(exp, group, stayer, leaver):
        barrier = GroupBarrier(
            "late", group_type="main", late_after=5, late_action=late_action
        )
        _arrive(exp, barrier, [stayer])
        _set_group_clocks_in_the_past(group, seconds=10)
        barrier.check_waiting_participants([stayer])
        return leaver

    return remove


def _waited_too_long(exp, group, stayer, leaver):
    barrier = GroupBarrier("wait", group_type="main", max_wait_action="leave_group")
    _arrive(exp, barrier, [stayer])
    barrier.handle_max_wait_timeout(stayer)
    return stayer


def _removed_by_experimenter(exp, group, stayer, leaver):
    group.remove_participant(leaver, reason="removed_by_experimenter")
    return leaver


def _dissolved_before_the_barrier(exp, group, stayer, leaver):
    leaver.fail("returned")
    return stayer


def _dissolved_and_failed(exp, group, stayer, leaver):
    group.below_quorum = "fail"
    leaver.fail("returned")
    return stayer


def _late_after_complete(exp, group, stayer, leaver):
    leaver.current_trial.complete = True
    group.remove_participant(leaver, reason="late")
    return leaver


def _dissolved_after_complete(exp, group, stayer, leaver):
    _arrive(exp, GroupBarrier("done", group_type="main"), [stayer, leaver])
    stayer.current_trial.complete = True
    leaver.fail("returned")
    return stayer


def _dissolved_after_release(exp, group, stayer, leaver):
    _arrive(exp, GroupBarrier("done", group_type="main"), [stayer, leaver])
    leaver.fail("returned")
    return stayer


@pytest.mark.parametrize(
    "remove, outcome, n, fails",
    [
        (_late_at_barrier("fail"), "late", 2, True),
        (_late_at_barrier("fail"), "late", 3, True),
        (_late_at_barrier("leave_group"), "late", 2, False),
        (_waited_too_long, "waited_too_long", 2, False),
        (_removed_by_experimenter, "removed_by_experimenter", 2, False),
        (_dissolved_before_the_barrier, "group_dissolved", 2, False),
        (_dissolved_and_failed, "group_dissolved", 2, True),
        (_late_after_complete, None, 2, False),
        (_dissolved_after_complete, "stayed", 2, False),
        (_dissolved_after_release, "stayed", 2, False),
    ],
    ids=[
        "fail",
        "fail_two_of_a_trio",
        "leave_group",
        "max_wait",
        "default_reason",
        "dissolved",
        "dissolved_and_failed",
        "complete",
        "dissolved_after_complete",
        "dissolved_after_release",
    ],
)
@in_consents_experiment
def test_the_outcome_records_why_a_player_left_the_round(
    in_experiment_directory, db_session, remove, outcome, n, fails
):
    exp = get_experiment()
    members, group = _sync_group_of(exp, db_session, n)
    stayer, leaver = members[0], members[-1]
    group.below_quorum = "continue_without_group"
    for participant in members:
        TeamTrial.cue()[0].consume(exp, participant)
    db.session.commit()

    removed = remove(exp, group, stayer, leaver)
    db.session.commit()
    assert removed.current_trial.sync_group_outcome == outcome
    assert removed.failed == fails
    if fails:
        assert removed.sync_group_removal_reason("main") == outcome
    for other_leaver in members[1:-1]:
        assert other_leaver.current_trial.sync_group_outcome == outcome


def _dissolved_mid_round(exp, members):
    members[-1].fail("returned")


def _released_then_dissolved(exp, members):
    _arrive(exp, GroupBarrier("done", group_type="main"), members)
    members[-1].fail("returned")


def _dissolved_between_rounds(exp, members):
    _complete_trials(members)
    members[-1].fail("returned")


@pytest.mark.parametrize(
    "dissolve, marked",
    [
        (_dissolved_mid_round, True),
        (_released_then_dissolved, False),
        (_dissolved_between_rounds, False),
    ],
    ids=["mid_round", "after_release", "between_rounds"],
)
@in_consents_experiment
def test_a_round_records_that_its_group_dissolved_during_it(
    in_experiment_directory, db_session, dissolve, marked
):
    exp = get_experiment()
    members, group = _sync_group_of(exp, db_session, 2)
    group.below_quorum = "continue_without_group"
    _cue_team(exp, members, 0)
    db.session.commit()
    group_round = members[0].current_trial.group_round

    dissolve(exp, members)
    db.session.commit()
    assert not group.active
    assert (group_round.dissolved_at is not None) == marked


@in_consents_experiment
def test_dissolving_sees_a_release_another_request_committed(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    members, group = _sync_group_of(exp, db_session, 2)
    group.below_quorum = "continue_without_group"
    _cue_team(exp, members, 0)
    db.session.commit()
    group_round = members[0].current_trial.group_round
    assert group_round.closed_at is None

    with db.engine.begin() as barrier_request:
        barrier_request.execute(
            text("UPDATE sync_group_round SET closed_at = now() WHERE id = :id"),
            {"id": group_round.id},
        )
    members[-1].fail("returned")
    db.session.commit()
    assert not group.active and group_round.dissolved_at is None


@pytest.mark.parametrize("late_action", ["fail", "leave_group"])
@in_consents_experiment
def test_late_removal_waits_for_a_busy_late_member_then_removes_both(
    in_experiment_directory, db_session, late_action
):
    """Nobody is removed while one late member's own request holds their row."""
    exp = get_experiment()
    (stayer, *late), group = _sync_group_of(exp, db_session, 3)
    group.below_quorum = "continue_without_group"
    barrier = GroupBarrier(
        "late", group_type="main", late_after=5, late_action=late_action
    )
    _arrive(exp, barrier, [stayer])
    _set_group_clocks_in_the_past(group, seconds=10)
    db.session.commit()
    ids = [p.id for p in late]

    with db.engine.connect() as busy_request, busy_request.begin():
        busy_request.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": ids[1]},
        )
        _set_transaction_lock_timeout(1)
        barrier.check_waiting_participants([stayer])
        db.session.commit()
        assert "main" in Participant.query.get(ids[0]).active_sync_groups

    barrier.check_waiting_participants([stayer])
    db.session.commit()
    for participant_id in ids:
        participant = Participant.query.get(participant_id)
        assert participant.failed == (late_action == "fail")
        assert participant.sync_group_removal_reason("main") == "late"


@pytest.mark.parametrize("late_action", ["fail", "leave_group"])
@in_consents_experiment
def test_late_removal_rechecks_a_stale_list_of_waiting_members(
    in_experiment_directory, db_session, late_action
):
    """Lateness is rechecked once the member's row is locked.

    The check is given only the waiters it read before the late member's
    arrival committed.
    """
    exp = get_experiment()
    (stayer, late), group = _sync_group_of(exp, db_session, 2)
    barrier = GroupBarrier(
        "late", group_type="main", late_after=5, late_action=late_action
    )
    _arrive(exp, barrier, [stayer])
    _set_group_clocks_in_the_past(group, seconds=10)
    _arrive_at_group_barrier(exp, barrier, late)
    db.session.commit()

    barrier.check_waiting_participants([stayer])
    db.session.commit()
    assert not late.failed
    assert "main" in late.active_sync_groups


@in_consents_experiment
def test_late_removal_rechecks_a_timed_page_started_meanwhile(
    in_experiment_directory, db_session
):
    """A timed page the late member's request started since the group was read keeps them."""
    exp = get_experiment()
    (stayer, late), group = _sync_group_of(exp, db_session, 2)
    barrier = GroupBarrier("late", group_type="main", late_after=5, late_action="fail")
    _arrive(exp, barrier, [stayer])
    _set_group_clocks_in_the_past(group, seconds=10)
    db.session.commit()
    assert all(link.page_deadline is None for link in group.participant_links)

    with db.engine.begin() as late_request:
        late_request.execute(
            text(
                "UPDATE participant_link_sync_group "
                "SET page_deadline = now() + interval '1 minute' "
                "WHERE participant_id = :id"
            ),
            {"id": late.id},
        )

    barrier.check_waiting_participants([stayer])
    db.session.commit()
    assert not late.failed


@in_consents_experiment
def test_late_action_fail_leaves_other_groups_as_left_experiment(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (stayer, late), _ = _paired(exp)
    barrier = GroupBarrier("late", group_type="pair", late_after=5, late_action="fail")
    _arrive(exp, barrier, [stayer])
    _set_group_clocks_in_the_past(stayer.active_sync_groups["pair"], seconds=10)
    barrier.check_waiting_participants([stayer])
    assert late.sync_group_removal_reason("pair") == "late"
    assert late.sync_group_removal_reason("cohort") == "left_experiment"


# Case studies: each test below checks one case of
# docs/code/multiplayer/late_slow_and_leaving_players.rst; keep the two in step.


def _cue_team(exp, participants, i=None):
    for participant in participants:
        TeamTrial.cue({}, round=i)[0].consume(exp, participant)


def _waiting_at(barrier, participants):
    return [p for p in participants if barrier._participant_is_waiting(p)]


def _team_with_top_ups(exp, db_session):
    players, group = _sync_group_of(exp, db_session, 2)
    group.accepts_top_ups, group.max_group_size = True, 3
    (late,) = _working_participants(exp, 1)
    return players, late, group


_passes = []


def _record_pass(participants, left):
    _passes.append(([p.id for p in participants], [p.id for p in left]))


@in_consents_experiment
def test_case_a_fixed_pair_waits_only_for_the_slower_partner(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (fast, slow), _ = _sync_group_of(exp, db_session, 2)
    _cue_team(exp, [fast, slow], 0)
    _passes.clear()
    submitted = GroupBarrier("submitted", group_type="main", on_release=_record_pass)
    _arrive(exp, submitted, [fast])
    assert _waiting_at(submitted, [fast]) == [fast]
    _arrive(exp, submitted, [slow])
    assert _waiting_at(submitted, [fast, slow]) == []
    assert len(_passes) == 1 and fast.current_trial.group_round.closed_at
    assert [p.current_trial.sync_group_outcome for p in (fast, slow)] == [
        "stayed",
        "stayed",
    ]


@in_consents_experiment
def test_a_late_joiner_joins_the_open_round_and_its_barrier_waits_for_them(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (first, second), late, group = _team_with_top_ups(exp, db_session)
    _cue_team(exp, [first, second], 0)
    _passes.clear()
    submitted = GroupBarrier(
        "submitted",
        group_type="main",
        late_after=5,
        late_action="fail",
        on_release=_record_pass,
    )
    _arrive(exp, submitted, [first])
    _set_group_clocks_in_the_past(group, seconds=10)
    group.add_participant(late)
    _arrive(exp, submitted, [second])
    # late_after counts for the newcomer from when they joined.
    submitted.check_waiting_participants([first, second])
    assert not late.failed
    assert _waiting_at(submitted, [first, second]) == [first, second]

    _cue_team(exp, [late], 0)
    assert late.current_trial.group_round is first.current_trial.group_round
    _arrive(exp, submitted, [late])
    assert _waiting_at(submitted, [first, second, late]) == []
    assert [sorted(ids) for ids, _ in _passes] == [
        sorted(p.id for p in (first, second, late))
    ]


@pytest.mark.parametrize("n", [3, 2])
@in_consents_experiment
def test_case_a_member_leaves_mid_round(in_experiment_directory, db_session, n):
    exp = get_experiment()
    (*stayers, leaver), group = _sync_group_of(exp, db_session, n)
    group.quorum = 2
    group.below_quorum = "continue_without_group"
    _cue_team(exp, [*stayers, leaver], 0)
    _passes.clear()
    submitted = GroupBarrier("submitted", group_type="main", on_release=_record_pass)
    _arrive(exp, submitted, stayers)
    assert _waiting_at(submitted, stayers) == stayers

    leaver.fail("returned")
    db.session.commit()
    assert submitted.choose_who_to_release(stayers) == stayers
    if n == 3:
        assert _passes == [([p.id for p in stayers], [leaver.id])]
        assert {p.current_trial.sync_group_outcome for p in stayers} == {"stayed"}
    else:
        assert _passes == []
        assert stayers[0].current_trial.sync_group_outcome == "group_dissolved"
        assert stayers[0].group_removal_notice["text"] == (
            "Your partner is no longer in your group. Please continue."
        )


@in_consents_experiment
def test_case_a_slow_reader_between_runs_of_a_looped_module(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (fast, slow), _ = _sync_group_of(exp, db_session, 2)
    game = Module("game", InfoPage("Hi", time_estimate=1))
    answered = GroupBarrier("answered", group_type="main")
    for participant in (fast, slow):
        participant.start_module(game)
    _cue_team(exp, [fast, slow])
    _arrive(exp, answered, [fast, slow])
    _complete_trials([fast, slow])
    # The slow member is still on the results page at the end of run 1.
    fast.end_module(game)
    fast.start_module(game)
    _cue_team(exp, [fast])
    _arrive(exp, answered, [fast])
    assert _waiting_at(answered, [fast]) == [fast]

    slow.end_module(game)
    slow.start_module(game)
    _cue_team(exp, [slow])
    assert slow.current_trial.group_round is fast.current_trial.group_round
    _arrive(exp, answered, [slow])
    assert _waiting_at(answered, [fast, slow]) == []


@pytest.mark.parametrize(
    "max_wait_action, below_quorum, shared_cohort, waiter_fails, absent_fails",
    [
        ("fail", "fail", False, True, True),
        ("fail", "fail", True, True, True),
        ("fail", "continue_without_group", False, True, False),
        ("fail", "continue_without_group", True, True, False),
        ("leave_group", "fail", False, False, True),
        ("leave_group", "continue_without_group", False, False, False),
    ],
)
@in_consents_experiment
def test_case_max_wait_time_runs_out(
    in_experiment_directory,
    db_session,
    max_wait_action,
    below_quorum,
    shared_cohort,
    waiter_fails,
    absent_fails,
):
    exp = get_experiment()
    (waiter, absent), group = _sync_group_of(exp, db_session, 2)
    group.below_quorum = below_quorum
    if shared_cohort:
        cohort = SimpleSyncGroup(
            group_type="cohort",
            initial_group_size=2,
            max_group_size=2,
            quorum=2,
            n_active_participants=2,
            below_quorum=below_quorum,
            accepts_top_ups=False,
        )
        db_session.add(cohort)
        for participant in (waiter, absent):
            cohort.add_participant(participant)
    _cue_team(exp, [waiter, absent], 0)
    _passes.clear()
    submitted = GroupBarrier(
        "submitted",
        group_type="main",
        max_wait_action=max_wait_action,
        on_release=_record_pass,
    )
    _arrive(exp, submitted, [waiter])
    submitted.waiting_logic.apply_timeout(waiter)
    db.session.commit()

    assert _waiting_at(submitted, [waiter]) == [] and _passes == []
    assert (waiter.failed, absent.failed) == (waiter_fails, absent_fails)
    assert waiter.current_trial.sync_group_outcome == "waited_too_long"
    assert waiter.sync_group_removal_reason("main") == "waited_too_long"
    if shared_cohort:
        assert waiter.sync_group_removal_reason("cohort") == "left_experiment"
    if waiter_fails:
        assert "fail_on_timeout" in waiter.failure_tags
        assert "sync group below quorum" not in waiter.failure_tags
        assert waiter.group_removal_notice is None
    else:
        assert waiter.group_removal_notice["text"] == (
            "Your partner didn't arrive in time. Please continue."
        )
    assert absent.current_trial.sync_group_outcome == "group_dissolved"


@in_consents_experiment
def test_case_a_group_dissolves_under_a_member_on_a_round_page(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (waiter, reader, quitter), group = _sync_group_of(exp, db_session, 3)
    group.below_quorum = "continue_without_group"
    _cue_team(exp, [waiter, reader, quitter], 0)
    submitted = GroupBarrier("submitted", group_type="main")
    _arrive(exp, submitted, [waiter])
    quitter.fail("returned")
    db.session.commit()

    assert [p.current_trial.sync_group_outcome for p in (waiter, reader)] == [
        "group_dissolved",
        "group_dissolved",
    ]
    assert reader.current_trial.group_round.dissolved_at is not None
    original = exp.timeline
    exp.timeline = Timeline(
        submitted, ModularPage("after", "Round over", time_estimate=1)
    )
    try:
        payload = _json_timeline(exp, reader)
        assert exp.timeline.get_current_elt(exp, reader).label == "after"
    finally:
        exp.timeline = original
    assert payload.get_json()["attributes"]["arrival_updates"]["notice"] == (
        "Too few members of your group remained. Please continue."
    )
