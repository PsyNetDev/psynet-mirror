"""Tests for :meth:`Trial.cue` with a trial class that has ``sync_group_type``."""

import logging
import sys
import threading
import time
from pathlib import Path

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import GroupBarrier
from psynet.timeline import Module
from psynet.trial.chain import ChainNode
from psynet.trial.main import GenericTrialNetwork, SyncGroupNode, Trial
from psynet.trial.static import StaticNode, StaticTrialMaker

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from test_regrouper import _arrive, _cohort_and_pairs  # noqa: E402
from test_sync import _sync_group_of  # noqa: E402
from timeline_hold_helpers import _working_participants  # noqa: E402

in_consents_experiment = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)

_definition_calls = []


def _make_definition(group, round):
    _definition_calls.append((group.id, round))
    return {"target": round}


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

    pair.remove_participant(cohort[0])
    assert trials[0].sync_group is pair
    PairTrial.cue({"target": 9})[0].consume(exp, cohort[0])
    ungrouped = cohort[0].current_trial
    assert ungrouped.sync_group_id is None
    assert not isinstance(ungrouped.node, SyncGroupNode)


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


@in_consents_experiment
def test_an_explicit_round_lets_two_classes_share_a_node(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    PairTrial.cue(lambda: {"target": 1}, round=4)[0].consume(exp, cohort[0])
    VoteTrial.cue({"target": 1}, round=4)[0].consume(exp, cohort[0])
    with pytest.raises(ValueError, match="already has the definition"):
        VoteTrial.cue({"target": 2}, round=4)[0].consume(exp, cohort[1])
    PairTrial.cue({"target": 1})[0].consume(exp, cohort[0])
    db.session.commit()

    assert [t.sync_group_round for t in Trial.query.order_by(Trial.id)] == [4, 4, 5]
    assert SyncGroupNode.query.count() == 2


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
    # Round 0 ends: one trial completes, one fails, and a member with an
    # unfinished trial leaves.
    cohort[0].current_trial.complete = True
    cohort[1].current_trial.failed = True
    pair.remove_participant(early)
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
