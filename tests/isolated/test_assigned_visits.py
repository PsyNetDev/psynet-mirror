import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


class VisitRating(StaticTrial):
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
def test_visits_survive_transactions_and_distinguish_repeated_nodes(
    db_session, monkeypatch
):
    experiment = get_experiment()
    maker = StaticTrialMaker(
        id_="revisited_art",
        trial_class=VisitRating,
        nodes=[StaticNode(definition={"art": "a"})],
        expected_trials_per_participant=2,
        max_trials_per_participant=2,
        node_order=lambda nodes: [nodes[0], nodes[0]],
        allow_repeated_nodes=True,
    )
    monkeypatch.setattr("psynet.experiment.get_trial_maker", lambda id_: maker)
    maker.create_networks_across(experiment)
    alice, bob = (start_run(experiment, maker) for _ in range(2))
    first, second = maker.assign_visits(alice)
    other = maker.assign_visits(bob)[0]
    assert first.node_id == second.node_id == other.node_id
    assert len({first.id, second.id, other.id}) == 3
    with pytest.raises(ValueError, match="another participant"):
        first.complete(bob, False)
    with pytest.raises(ValueError, match="presentation order"):
        second.complete(alice, False)
    first_id, second_id, participant_id = first.id, second.id, alice.id
    db.session.commit()

    # A failed event batch must leave the vote available for delivery again.
    first.complete(alice, False, 0.8)
    db.session.rollback()
    db.session.remove()
    alice = db.session.get(Participant, participant_id)
    first, second = maker.assign_visits(alice)
    assert (first.id, second.id) == (first_id, second_id)
    assert first.trial_id is None
    trial = first.complete(alice, False, 0.8)
    assert isinstance(trial, VisitRating)
    db.session.commit()
    assert first.complete(alice, False, 0.8).id == trial.id
    with pytest.raises(ValueError, match="Conflicting replay"):
        first.complete(alice, True, 0.8)
    plan = maker.trial_plan(alice)
    assert plan["definitions"] == [{"art": "a"}, {"art": "a"}]
    assert plan["answers"] == [False]
    assert second.complete(alice, None).node_id == trial.node_id
    assert maker.trial_plan(alice)["answers"] == [False, None]
    assert (
        alice.module_state.n_completed_trials
        == alice.module_state.n_created_trials
        == 2
    )
