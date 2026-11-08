"""Tests for :meth:`Trial.cue` with a trial class that has ``sync_group_type``."""

import sys
import threading
import time
from pathlib import Path

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import GroupBarrier
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


class RespondTrial(PairTrial):
    pass


class VoteTrial(Trial):
    time_estimate = 1
    sync_group_type = "pair"


@in_consents_experiment
def test_trial_classes_in_one_round_share_its_node_and_definition(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    # A subclass, then its parent, then an unrelated class: all in round 0.
    for trial_class in (RespondTrial, PairTrial, VoteTrial):
        trial_class.cue({"target": 1})[0].consume(exp, cohort[0])
    db.session.commit()

    assert SyncGroupNode.query.count() == 1
    assert {t.sync_group_round for t in Trial.query} == {0}
    with pytest.raises(ValueError, match="already has the definition"):
        PairTrial.cue({"target": 2})[0].consume(exp, cohort[1])


@in_consents_experiment
def test_a_late_joiner_joins_the_group_s_current_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, _ = _paired(exp)
    pair = cohort[0].active_sync_groups["pair"]
    (late,) = _working_participants(exp, 1)
    logic = PairTrial.cue({"target": 1})
    for participant in cohort:
        logic[0].consume(exp, participant)
    pair.add_participant(late)
    logic[0].consume(exp, late)
    db.session.commit()

    assert {(t.node_id, t.sync_group_round) for t in PairTrial.query} == {
        (SyncGroupNode.query.one().id, 0)
    }


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
        return trial, "available"


@in_consents_experiment
def test_a_synchronized_trial_maker_records_group_role_and_round(
    in_experiment_directory, db_session
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
    for round in (0, 1):
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
