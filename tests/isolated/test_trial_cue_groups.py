"""Tests for :meth:`Trial.cue` with a trial class that has ``sync_group_type``."""

import logging
import sys
import threading
import time
from pathlib import Path

import pytest
from dallinger import db
from sqlalchemy import text

import psynet.sync
from psynet.db import _set_transaction_lock_timeout
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    GroupBarrier,
    _hold_barrier_instance_claim,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
)
from psynet.timeline import Module, Timeline
from psynet.trial.chain import ChainNode
from psynet.trial.main import GenericTrialNetwork, SyncGroupNode, Trial
from psynet.trial.static import StaticNode, StaticTrialMaker

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from test_regrouper import _arrive, _cohort_and_pairs  # noqa: E402
from test_sync import (  # noqa: E402
    _arrive_at_group_barrier,
    _backdate_group,
    _sync_group_of,
)
from timeline_hold_helpers import _json_timeline, _working_participants  # noqa: E402

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
    def score_pair(cls, trials, node):
        node.var.players = [trial.participant_id for trial in trials]
        for trial in trials:
            trial.var.scored = True

    @classmethod
    def record_release(cls, participants, trials, node):
        _released.append((participants, trials, node))


_released = []


def _paired(exp):
    cohort, pairs = _cohort_and_pairs(exp, 2)
    _arrive(exp, pairs, cohort)
    _definition_calls.clear()
    return cohort, pairs


@in_consents_experiment
def test_a_pair_s_cued_trials_share_one_node_per_round(
    in_experiment_directory, db_session
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
    roles = [pairs.role(p) for p in cohort]
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
    nodes = [t.node for t in trials]
    assert isinstance(nodes[0], SyncGroupNode)
    assert nodes[0] is nodes[1] and nodes[2] is nodes[3] and nodes[0] is not nodes[2]
    assert nodes[0].network is nodes[2].network
    PairTrial.cue({"target": 7})[0].consume(exp, cohort[0])
    with pytest.raises(ValueError, match="already has the definition"):
        PairTrial.cue({"target": 8})[0].consume(exp, cohort[1])

    pair.remove_participant(cohort[0])
    assert trials[0].sync_group is pair
    PairTrial.cue({"target": 9})[0].consume(exp, cohort[0])
    ungrouped = cohort[0].current_trial
    assert ungrouped.sync_group_id is None
    assert not isinstance(ungrouped.node, SyncGroupNode)
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
    assert sorted(trials[0].node.var.players) == [p.id for p in cohort]
    assert all(trial.var.scored for trial in trials)


@in_consents_experiment
def test_each_trial_records_how_its_round_ended_for_the_player(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    stayer, leaver = cohort
    pair = stayer.active_sync_groups["pair"]
    for participant in cohort:
        PairTrial.cue(round=0)[0].consume(exp, participant)
    _arrive(exp, GroupBarrier("offered", group_type="pair"), cohort)
    # Leaving before the trial's pages end replaces an earlier barrier's release.
    pair.remove_participant(leaver, reason="late")
    _arrive(exp, GroupBarrier("answered", group_type="pair"), [stayer])
    assert [p.current_trial.sync_group_outcome for p in cohort] == ["stayed", "late"]

    stayer.current_trial.complete = True
    pair.remove_participant(stayer, reason="finished")
    assert stayer.current_trial.sync_group_outcome == "stayed"
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
def test_a_waiting_screen_gets_the_trial_and_its_node(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    PairTrial.cue()[0].consume(exp, cohort[0])
    hold = GroupBarrier(
        "answered", group_type="pair", waiting_screen=_trial_and_node_screen
    ).waiting_logic

    trial = cohort[0].current_trial
    screen = hold.waiting_screen_page(cohort[0])
    assert screen.prompt.text == f"Trial {trial.id} on node {trial.node.id}"
    assert hold.waiting_screen_page(cohort[1]).prompt.text == "Trial None on node None"


def _trial_and_node_screen(trial, node):
    return f"Trial {getattr(trial, 'id', None)} on node {getattr(node, 'id', None)}"


@in_consents_experiment
def test_only_ungrouped_trials_check_their_time_credit(
    in_experiment_directory, db_session, caplog
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    PairTrial.cue({})[0].consume(exp, cohort[0])
    pair.remove_participant(cohort[1])
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
    assert {p.current_trial.node_id for p in cohort} == {newcomer.current_trial.node_id}


@in_consents_experiment
def test_a_barrier_after_the_trial_waits_for_every_member_and_gets_no_node(
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

    ((participants, trials, node),) = _released
    assert node is None
    assert {p.id: t for p, t in zip(participants, trials)} == {
        p.id: p.current_trial for p in [*cohort, newcomer]
    }
    assert not cohort[0].current_trial.node.sync_group_closed
    assert [p.current_trial.sync_group_outcome for p in cohort] == [None, None]


@in_consents_experiment
def test_a_release_waits_for_a_cue_holding_the_round_lock(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    for participant in cohort:
        PairTrial.cue({"target": 1})[0].consume(exp, participant)
    db.session.commit()
    node = cohort[0].current_trial.node
    barrier = GroupBarrier("submitted", group_type="pair")
    key = f"sync_group_node:{node.module_id}:{node.sync_group_id}"

    with db.engine.connect() as cue_request, cue_request.begin():
        cue_request.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )
        assert not barrier.would_release(cohort)
        assert barrier.choose_who_to_release(cohort) == []
    assert not node.sync_group_closed
    assert barrier.would_release(cohort)
    released = barrier.choose_who_to_release(cohort)
    assert {p.id for p in released} == {p.id for p in cohort}
    assert node.sync_group_closed


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
def test_members_cueing_in_parallel_get_one_node(in_experiment_directory, db_session):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    _cue_in_parallel(exp, PairTrial.cue(_make_definition), cohort)

    assert SyncGroupNode.query.count() == 1
    assert {t.node_id for t in PairTrial.query} == {SyncGroupNode.query.one().id}
    assert len(_definition_calls) == 1


class SoloTrial(Trial):
    time_estimate = 1

    def show_trial(self, experiment, participant):
        raise NotImplementedError

    @classmethod
    def record_node(cls, node):
        _released_nodes.append(node)


_released_nodes = []


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
    with pytest.raises(TypeError, match="makes the group's node itself"):
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

    assert sorted((n.module_id, n.sync_group_round) for n in SyncGroupNode.query) == [
        ("main", 0),
        ("practice", 0),
    ]


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

    ((participants, trials, node),) = _released
    assert node is None
    assert {p.id: t for p, t in zip(participants, trials)} == {
        t.participant_id: t for t in first_trials
    }
    assert [t.sync_group_outcome for t in first_trials] == [None, None]
    assert not first_trials[0].node.sync_group_closed
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

    ((_, _, node),) = _released
    assert node is None
    assert [t.sync_group_outcome for t in first_trials] == [None, None]
    assert not first_trials[0].node.sync_group_closed


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
    trials[0].node.sync_group_closed = round_closed
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
    assert cohort[0].current_trial.node is cohort[1].current_trial.node


@in_consents_experiment
def test_an_explicit_round_lets_two_classes_share_a_node(
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
    assert SyncGroupNode.query.count() == 2


@in_consents_experiment
def test_an_explicit_round_skips_a_round_the_group_finished_without_the_player(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    (newcomer,) = _working_participants(exp, 1)

    def cue(participant, i):
        PairTrial.cue({"target": i}, round=i)[0].consume(exp, participant)
        return participant.current_trial

    for participant in cohort:
        cue(participant, 0)
    _arrive(exp, GroupBarrier("answered", group_type="pair"), cohort)
    for participant in cohort:
        cue(participant, 1)
    pair.add_participant(newcomer)

    assert cue(newcomer, 0) is None
    joined = cue(newcomer, 1)
    assert joined.node is cohort[0].current_trial.node
    assert joined.definition == {"target": 1}
    pair.remove_participant(cohort[1])
    alone = cue(cohort[1], 2)
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
        node = cohort[0].current_trial.node
        assert node.sync_group_round == i
        assert sorted(node.var.players) == [p.id for p in cohort]


@in_consents_experiment
def test_a_skipped_cue_moves_on_to_the_next_page(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    for participant in cohort:
        PairTrial.cue({}, round=0)[0].consume(exp, participant)
    _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
    (newcomer,) = _working_participants(exp, 1)
    pair.add_participant(newcomer)
    after = InfoPage("After the round", time_estimate=5)
    timeline = Timeline(
        InfoPage("Before the round", time_estimate=5),
        PairTrial.cue({}, round=0),
        after,
    )
    monkeypatch.setattr(exp, "timeline", timeline)
    timeline.advance_page(exp, newcomer)
    credit, progress = newcomer.time_credit, newcomer.progress

    timeline.advance_page(exp, newcomer)
    assert timeline.get_current_elt(exp, newcomer) is after
    assert newcomer.current_trial is None
    assert newcomer.time_credit == credit
    assert newcomer.progress > progress


_releases = []


def _record_release(participants):
    _releases.append(sorted(p.id for p in participants))


@in_consents_experiment
def test_a_barrier_after_the_loop_waits_for_a_skipper(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    for participant in cohort:
        _cue_round(exp, participant, 0)
    _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
    (newcomer,) = _working_participants(exp, 1)
    pair.add_participant(newcomer)
    _complete_trials(cohort)
    _releases.clear()
    after_loop = GroupBarrier(
        "after_loop", group_type="pair", on_release=_record_release
    )
    _arrive(exp, after_loop, cohort)
    assert after_loop._participant_is_waiting(cohort[0])

    assert _cue_round(exp, newcomer, 0) is None
    _arrive(exp, after_loop, [newcomer])
    assert _releases == [sorted(p.id for p in [*cohort, newcomer])]


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
    in_round = GroupBarrier("submitted", group_type="pair", late_after=5)
    _arrive(exp, in_round, cohort[:1])
    _arrive(exp, GroupBarrier("ready", group_type="pair", late_after=5), [newcomer])
    _backdate_group(pair, seconds=10)
    in_round.check_waiting_participants(cohort[:1])
    # The round waits for the newcomer, who isn't at its barrier.
    assert cohort[1].failed and newcomer.failed


@pytest.mark.parametrize("in_tests", [True, False])
@in_consents_experiment
def test_members_waiting_for_each_other_at_different_barriers_are_reported(
    in_experiment_directory, db_session, caplog, monkeypatch, in_tests
):
    monkeypatch.setattr(psynet.sync, "_in_tests", lambda: in_tests)
    monkeypatch.setattr(psynet.sync, "_reported_divergences", set())
    exp = get_experiment()
    cohort, newcomer, _ = _newcomer_in_round_0(exp)
    in_round = GroupBarrier("submitted", group_type="pair")
    # A barrier at the start of each iteration, which the newcomer reaches first.
    start = GroupBarrier("ready", group_type="pair")
    _arrive(exp, in_round, cohort[:1])
    _arrive(exp, start, [newcomer])
    with caplog.at_level(logging.ERROR):
        if in_tests:
            with pytest.raises(psynet.sync.GroupDivergenceError, match="'ready' has"):
                _arrive(exp, in_round, cohort[1:])
            return
        _arrive(exp, in_round, cohort[1:])
        start.choose_who_to_release([newcomer])
    (error,) = [r for r in caplog.records if "wait for each other" in r.getMessage()]
    assert error.levelname == "ERROR" and "'submitted' has" in error.getMessage()
    assert all(in_round._participant_is_waiting(p) for p in cohort)


@in_consents_experiment
def test_divergence_is_reported_when_the_poller_holds_the_last_arrival_s_visit(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, newcomer, _ = _newcomer_in_round_0(exp)
    in_round = GroupBarrier("submitted", group_type="pair")
    _arrive(exp, in_round, cohort[:1])
    _arrive(exp, GroupBarrier("ready", group_type="pair"), [newcomer])
    _arrive_at_group_barrier(exp, in_round, cohort[1])
    db.session.commit()
    checks = _take_pending_barrier_checks()
    with _hold_barrier_instance_claim(checks[0]) as claimed:
        assert claimed
        with pytest.raises(psynet.sync.GroupDivergenceError):
            _run_pending_barrier_checks(checks, wait=False)


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
    "module_ids, n_rounds, skipper",
    [
        (["a"], 1, False),
        (["a"], 2, False),
        (["a"], 2, True),
        (["a", "b", "a"], 0, False),
    ],
)
@in_consents_experiment
def test_cueing_a_played_or_skipped_round_again_raises(
    in_experiment_directory, db_session, module_ids, n_rounds, skipper
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    (newcomer,) = _working_participants(exp, 1)
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
    for participant in [*cohort, newcomer]:
        participant.start_module(module)
    players = cohort
    for i in range(n_rounds):
        for participant in players:
            _cue_round(exp, participant, i)
        _arrive(exp, GroupBarrier("submitted", group_type="pair"), players)
        if skipper and i == 0:
            pair.add_participant(newcomer)
            assert _cue_round(exp, newcomer, 0) is None
            players = [*cohort, newcomer]
    with pytest.raises(RuntimeError, match="again"):
        _cue_round(exp, players[-1], 0)


@pytest.mark.parametrize("round_closed", [True, False])
@in_consents_experiment
def test_a_member_who_rejoined_skips_a_round_they_played(
    in_experiment_directory, db_session, round_closed
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    for participant in cohort:
        _cue_round(exp, participant, 0)
    if round_closed:
        _arrive(exp, GroupBarrier("submitted", group_type="pair"), cohort)
    pair.remove_participant(cohort[0], reason="moved_on")
    pair.add_participant(cohort[0])
    assert _cue_round(exp, cohort[0], 0) is None
    assert PairTrial.query.filter_by(participant_id=cohort[0].id).count() == 1


@pytest.mark.parametrize("skipper_first", [False, True])
@in_consents_experiment
def test_a_skipper_releases_with_the_players_at_a_barrier_s_second_pass(
    in_experiment_directory, db_session, skipper_first
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    for participant in cohort:
        _cue_round(exp, participant, 0)
    # The players pass "sync" in the trial, then again after it with the skipper.
    _arrive(exp, GroupBarrier("sync", group_type="pair"), cohort)
    _complete_trials(cohort)
    (newcomer,) = _working_participants(exp, 1)
    pair.add_participant(newcomer)
    assert _cue_round(exp, newcomer, 0) is None
    sync = GroupBarrier("sync", group_type="pair")
    first = [newcomer] if skipper_first else [cohort[0], newcomer]
    _arrive(exp, sync, first)
    assert sync._participant_is_waiting(newcomer)
    _arrive(exp, sync, [p for p in cohort if p not in first])
    assert not any(sync._participant_is_waiting(p) for p in [newcomer, *cohort])


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
    assert SyncGroupNode.query.count() == 2


@in_consents_experiment
def test_on_release_gets_no_node_for_trials_off_the_group_s_node(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    logic = SoloTrial.cue({"target": 1})
    for participant in cohort:
        logic[0].consume(exp, participant)
    db.session.commit()
    _released_nodes.clear()

    barrier = GroupBarrier(
        "solo_done", group_type="pair", on_release=SoloTrial.record_node
    )
    _arrive(exp, barrier, cohort)
    assert _released_nodes == [None]


class CustomStaticTrialMaker(StaticTrialMaker):
    """Prepares the leader's trials itself, as trial makers that override prepare_trial do."""

    def prepare_trial(self, experiment, participant):
        node = Trial.get_default_parent_node(participant, experiment)
        trial = PairTrial(experiment, node, participant, False, False, definition={})
        self._finalize_created_trial(trial)
        return trial, "available"


@in_consents_experiment
def test_a_synchronized_trial_maker_records_group_role_and_round(
    in_experiment_directory, db_session, caplog
):
    exp = get_experiment()
    cohort, pairs = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    trial_maker = CustomStaticTrialMaker(
        id_="paired_static",
        trial_class=PairTrial,
        nodes=[StaticNode(definition={})],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        sync_group_type="pair",
    )
    for participant in cohort:
        participant.start_module(trial_maker)

    members = [pair.leader, *pair.active_followers]
    for round in (0, 1, 2):
        if round == 2:
            # Repeat each player's last trial.
            for p in members:
                state = p.module_state
                state.in_repeat_phase = True
                state.trials_to_repeat = [p.current_trial.id]
                state.repeat_trial_index = 0
        trial_maker._try_to_prepare_trial_group(pair)
        db.session.flush()
        assert [
            (
                p.current_trial.sync_group_id,
                p.current_trial.sync_group_role,
                p.current_trial.sync_group_round,
            )
            for p in members
        ] == [(pair.id, pairs.role(p), round) for p in members]
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

    @classmethod
    def record_dissolve(cls, trials, node):
        _dissolved.append((trials, node))


_dissolved = []


@in_consents_experiment
def test_on_dissolve_gets_the_waiting_members_trials_and_node(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (waiter, quitter), group = _sync_group_of(exp, db_session, 2)
    group.below_quorum = "continue_without_group"
    logic = TeamTrial.cue({})
    for participant in (waiter, quitter):
        logic[0].consume(exp, participant)
    db.session.commit()
    _dissolved.clear()
    barrier = GroupBarrier(
        "team_done", group_type="main", on_dissolve=TeamTrial.record_dissolve
    )
    _arrive(exp, barrier, [waiter])

    quitter.fail("returned")
    db.session.commit()

    ((trials, node),) = _dissolved
    assert [t.participant_id for t in trials] == [waiter.id]
    assert node is trials[0].node and isinstance(node, SyncGroupNode)
    assert [p.current_trial.sync_group_outcome for p in (waiter, quitter)] == [
        "group_dissolved",
        "left_experiment",
    ]


def _late_at_barrier(late_action):
    def remove(exp, group, stayer, leaver):
        barrier = GroupBarrier(
            "late", group_type="main", late_after=5, late_action=late_action
        )
        _arrive(exp, barrier, [stayer])
        _backdate_group(group, seconds=10)
        barrier.check_waiting_participants([stayer])
        return leaver

    return remove


def _waited_too_long(exp, group, stayer, leaver):
    barrier = GroupBarrier("wait", group_type="main", max_wait_action="leave_group")
    _arrive(exp, barrier, [stayer])
    barrier.handle_max_wait_timeout(stayer)
    return stayer


def _removed_without_reason(exp, group, stayer, leaver):
    group.remove_participant(leaver)
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


@pytest.mark.parametrize(
    "remove, outcome, n, fails",
    [
        (_late_at_barrier("fail"), "late", 2, True),
        (_late_at_barrier("fail"), "late", 3, True),
        (_late_at_barrier("leave_group"), "late", 2, False),
        (_waited_too_long, "waited_too_long", 2, False),
        (_removed_without_reason, "removed", 2, False),
        (_dissolved_before_the_barrier, "group_dissolved", 2, False),
        (_dissolved_and_failed, "group_dissolved", 2, True),
        (_late_after_complete, "late", 2, False),
        (_dissolved_after_complete, "stayed", 2, False),
    ],
    ids=[
        "fail",
        "fail_two_of_a_trio",
        "leave_group",
        "max_wait",
        "no_reason",
        "dissolved",
        "dissolved_and_failed",
        "complete",
        "dissolved_after_complete",
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


@in_consents_experiment
def test_late_action_fail_waits_for_a_busy_late_member_then_fails_both(
    in_experiment_directory, db_session
):
    """Nobody is failed while one late member's own request holds their row."""
    exp = get_experiment()
    (stayer, *late), group = _sync_group_of(exp, db_session, 3)
    group.below_quorum = "continue_without_group"
    barrier = GroupBarrier("late", group_type="main", late_after=5, late_action="fail")
    _arrive(exp, barrier, [stayer])
    _backdate_group(group, seconds=10)
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
        assert not Participant.query.get(ids[0]).failed

    barrier.check_waiting_participants([stayer])
    db.session.commit()
    for participant_id in ids:
        participant = Participant.query.get(participant_id)
        assert participant.failed
        assert participant.sync_group_removal_reason("main") == "late"


@in_consents_experiment
def test_late_action_fail_leaves_other_groups_as_left_experiment(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (stayer, late), _ = _paired(exp)
    barrier = GroupBarrier("late", group_type="pair", late_after=5, late_action="fail")
    _arrive(exp, barrier, [stayer])
    _backdate_group(stayer.active_sync_groups["pair"], seconds=10)
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
    assert len(_passes) == 1 and fast.current_trial.node.sync_group_closed
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
        "submitted", group_type="main", late_after=5, on_release=_record_pass
    )
    _arrive(exp, submitted, [first])
    _backdate_group(group, seconds=10)
    group.add_participant(late)
    _arrive(exp, submitted, [second])
    # late_after counts for the newcomer from when they joined.
    submitted.check_waiting_participants([first, second])
    assert not late.failed
    assert _waiting_at(submitted, [first, second]) == [first, second]

    _cue_team(exp, [late], 0)
    assert late.current_trial.node is first.current_trial.node
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
    group.min_group_size = 2
    group.below_quorum = "continue_without_group"
    _cue_team(exp, [*stayers, leaver], 0)
    _passes.clear()
    _dissolved.clear()
    submitted = GroupBarrier(
        "submitted",
        group_type="main",
        on_release=_record_pass,
        on_dissolve=TeamTrial.record_dissolve,
    )
    _arrive(exp, submitted, stayers)
    assert _waiting_at(submitted, stayers) == stayers

    leaver.fail("returned")
    db.session.commit()
    assert submitted.choose_who_to_release(stayers) == stayers
    if n == 3:
        assert _passes == [([p.id for p in stayers], [leaver.id])]
        assert {p.current_trial.sync_group_outcome for p in stayers} == {"stayed"}
    else:
        ((trials, _),) = _dissolved
        assert _passes == [] and trials == [stayers[0].current_trial]
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
    assert slow.current_trial.node is fast.current_trial.node
    _arrive(exp, answered, [slow])
    assert _waiting_at(answered, [fast, slow]) == []


@pytest.mark.parametrize(
    "max_wait_action, below_quorum, waiter_fails, absent_fails",
    [
        ("fail", "fail", True, True),
        ("fail", "continue_without_group", True, False),
        ("leave_group", "fail", False, True),
        ("leave_group", "continue_without_group", False, False),
    ],
)
@in_consents_experiment
def test_case_max_wait_time_runs_out(
    in_experiment_directory,
    db_session,
    max_wait_action,
    below_quorum,
    waiter_fails,
    absent_fails,
):
    exp = get_experiment()
    (waiter, absent), group = _sync_group_of(exp, db_session, 2)
    group.below_quorum = below_quorum
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
    assert waiter.current_trial.sync_group_outcome == (
        "left_experiment" if waiter_fails else "waited_too_long"
    )
    if not waiter_fails:
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
    _dissolved.clear()
    submitted = GroupBarrier(
        "submitted", group_type="main", on_dissolve=TeamTrial.record_dissolve
    )
    _arrive(exp, submitted, [waiter])
    quitter.fail("returned")
    db.session.commit()

    ((trials, _),) = _dissolved
    assert trials == [waiter.current_trial]
    assert reader.current_trial.sync_group_outcome == "group_dissolved"
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
