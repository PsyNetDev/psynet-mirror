import uuid
from datetime import datetime, timedelta

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


class PreparedRating(StaticTrial):
    time_estimate = 1


def start_run(experiment, maker):
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.flush()
    state = maker.state_class(maker, participant)
    state.participant_group = "default"
    state.participated_networks = []
    state.block_order = ["default"]
    state.set_block_position(0)
    participant.module_state = state
    db.session.add(state)
    db.session.flush()
    return participant


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_prepared_trials_survive_breaks_and_time_out_only_when_open(
    db_session, monkeypatch
):
    experiment = get_experiment()
    maker = StaticTrialMaker(
        id_="prepared_art",
        trial_class=PreparedRating,
        nodes=[StaticNode(definition={"art": i}) for i in range(49)],
        expected_trials_per_participant=50,
        max_trials_per_participant=50,
        node_order=lambda nodes: [*nodes, nodes[0]],
        allow_repeated_nodes=True,
    )
    monkeypatch.setattr("psynet.experiment.get_trial_maker", lambda id_: maker)
    maker.create_networks_across(experiment)
    alice, bob = (start_run(experiment, maker) for _ in range(2))
    items = maker.prepare_trials(alice)
    ids = [t.id for t in items]
    assert len(set(ids)) == alice.module_state.n_created_trials == 50
    assert [t.position for t in items] == list(range(50))
    assert items[0].node_id == items[-1].node_id
    assert alice.module_state.n_completed_trials == 0
    assert all(t.response_started_at is None for t in items)
    assert maker.trial_plan(alice)["_trial_ids"] == ids
    bob_items = maker.prepare_trials(bob)
    assert [t.node_id for t in bob_items] == [t.node_id for t in items]
    assert set(ids).isdisjoint(t.id for t in bob_items)
    # Simulate a long wait independent of the machine's clock.
    old = datetime.now() - timedelta(seconds=maker.response_timeout_sec + 60)
    for item in [*items, *bob_items]:
        item.creation_time = old
    alice_id, bob_id = alice.id, bob.id
    db.session.commit()

    first = items[0]
    with pytest.raises(ValueError, match="belong"):
        first.submit_response(bob, True)
    with pytest.raises(ValueError, match="not open"):
        first.submit_response(alice, True)
    with pytest.raises(ValueError, match="active sequence"):
        items[1].start_response(alice)
    first.start_response(alice)
    first.submit_response(alice, False, 0.8)
    db.session.rollback()
    db.session.remove()
    alice = db.session.get(Participant, alice_id)
    items = maker.prepare_trials(alice)
    assert [t.id for t in items] == ids
    assert items[0].response_started_at is None
    for item, answer in zip(items, [False, None, True]):
        item.start_response(alice)
        opened = item.response_started_at
        item.start_response(alice)
        assert item.response_started_at == opened
        item.submit_response(alice, answer, 0.8)
        item.submit_response(alice, answer, 0.8)
        assert item.finalized and item.complete
    with pytest.raises(ValueError, match="Conflicting replay"):
        items[0].submit_response(alice, True, 0.8)
    with pytest.raises(ValueError, match="Conflicting replay"):
        items[0].submit_response(alice, 0, 0.8)
    db.session.commit()
    maker.check_old_trials()
    assert not any(t.failed for t in items)
    assert maker.trial_plan(alice)["answers"] == [False, None, True]
    assert alice.module_state.n_completed_trials == 3
    fourth = items[3]
    assert fourth.response_started_at is None
    fourth.start_response(alice)
    fourth.response_started_at = old
    with monkeypatch.context() as scoped:
        scoped.setattr(maker, "response_timeout_sec", None)
        maker.check_old_trials()
        assert not fourth.failed
    with monkeypatch.context() as scoped:
        scoped.setattr(maker, "id", "another_trial_maker")
        maker.check_old_trials()
        assert not fourth.failed
    maker.check_old_trials()
    assert fourth.failed and fourth.failed_reason == "response_timeout"
    assert all(not t.failed and t.response_started_at is None for t in items[4:])
    with pytest.raises(ValueError, match="active sequence"):
        fourth.submit_response(alice, True)
    alice._fail_incomplete_trials("participant_exit")
    assert all(t.complete and not t.failed for t in items[:3])
    assert all(t.failed and not t.complete for t in items[3:])
    assert all(t.response_started_at is None for t in items[4:])
    assert alice.module_state.n_created_trials == 50
    assert alice.module_state.n_completed_trials == 3

    # A participant can also leave without a response timeout.
    bob = db.session.get(Participant, bob_id)
    bob_items = maker.prepare_trials(bob)
    for item in bob_items[:3]:
        item.start_response(bob)
        item.submit_response(bob, True)
    bob_items[3].start_response(bob)
    bob._fail_incomplete_trials("participant_exit")
    db.session.flush()
    assert all(t.complete and not t.failed for t in bob_items[:3])
    assert all(t.failed_reason == "participant_exit" for t in bob_items[3:])
    assert bob_items[3].response_started_at is not None
    assert all(t.response_started_at is None for t in bob_items[4:])


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_solo_resume_keeps_deadline_and_late_answers_do_not_advance(
    db_session, monkeypatch
):
    from types import SimpleNamespace

    from dallinger.models import RealtimeSession

    from psynet.live_game import LiveGameControl, PlayLiveGame
    from psynet.live_game.reward import _apply_prepared_trial
    from psynet.modular_page import ModularPage
    from psynet.prescreen.vocab_live import VocabularyGame

    experiment = get_experiment()
    maker = StaticTrialMaker(
        id_="solo_screen",
        trial_class=PreparedRating,
        nodes=[StaticNode(definition=i) for i in range(2)],
        expected_trials_per_participant=2,
        max_trials_per_participant=2,
        node_order="listed",
    )
    monkeypatch.setattr("psynet.experiment.get_trial_maker", lambda id_: maker)
    maker.create_networks_across(experiment)
    player = start_run(experiment, maker)
    first, second = maker.prepare_trials(player)
    run = player.module_state
    ended = []
    monkeypatch.setattr("psynet.live_game.play._end_expired_session", ended.append)

    def apply(session_id, trial, **data):
        row = SimpleNamespace(id=session_id, members=[player.id])
        _apply_prepared_trial({"player": 0, "trial_id": trial.id, **data}, row)

    def create_session(game_class, participants, settings):
        row = RealtimeSession(
            game_type=game_class.channel, members=[p.id for p in participants], bots=[]
        )
        db.session.add(row)
        db.session.flush()
        return row.id

    monkeypatch.setattr("psynet.live_game.play._create_game_session", create_session)
    solo = PlayLiveGame(
        game_class=VocabularyGame,
        page=ModularPage("words", "Play.", LiveGameControl(), time_estimate=2),
    ).solo
    solo._prepare(player)
    assert solo._pending(player)
    solo._start_segment(player)
    original = run.var.solo_trial_session
    apply(original, first)
    apply(original, first, answer=True, time_taken=0.5, next_id=second.id)
    apply(original, second, presented=True)
    opened = second.response_started_at
    transport = db.session.get(RealtimeSession, original)
    transport.status, transport.end_reason = "ended", "players_left"
    db.session.flush()
    assert solo._pending(player)
    solo._start_segment(player)
    resumed = run.var.solo_trial_session
    assert resumed != original
    assert [item.id for item in maker.prepare_trials(player)] == [first.id, second.id]
    apply(resumed, second)
    assert second.response_started_at == opened
    apply(resumed, second, presented=True)
    assert second.var.n_presentations == 2
    second.response_started_at = datetime.now() - timedelta(days=1)
    with monkeypatch.context() as scoped:
        scoped.setattr(maker, "response_timeout_sec", None)
        assert not second._expire_if_overdue()
    db.session.commit()
    apply(resumed, second, answer=False, time_taken=1, next_id=None)
    assert second.failed_reason == "response_timeout" and not second.complete
    db.session.rollback()
    assert ended == [] and not second.failed
    # The ordinary timeout sweep reaches the same terminal state without a click.
    maker.check_old_trials()
    db.session.commit()
    assert ended == [resumed]
    assert not solo._pending(player) and not solo._completed(player)
    assert run.n_completed_trials == 1 and first.answer is True
    assert second.failed_reason == "response_timeout" and second.answer is None
