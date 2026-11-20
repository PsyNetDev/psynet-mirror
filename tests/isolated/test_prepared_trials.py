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
    assert maker.trial_plan(alice, stop=3)["_trial_ids"] == ids[:3]
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
