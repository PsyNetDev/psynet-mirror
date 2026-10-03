import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import count_orm_loads
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

SMALL, LARGE = 10, 400


class ScalingTrial(StaticTrial):
    time_estimate = 1


def _loads_to_prepare_one_trial(n_nodes):
    """Return the ORM objects loaded while a fresh participant gets one trial."""
    exp = get_experiment()
    trial_maker = StaticTrialMaker(
        id_=f"scaling_{n_nodes}",
        trial_class=ScalingTrial,
        nodes=[StaticNode(definition={"i": i}) for i in range(n_nodes)],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        target_trials_per_node=2,
    )
    trial_maker.create_networks_across(exp)
    participant = Participant(
        experiment=exp,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.flush()
    state = trial_maker.state_class(trial_maker, participant)
    state.participant_group = "default"
    state.participated_networks = []
    state.block_order = ["default"]
    state.set_block_position(0)
    participant.module_state = state
    db.session.add(state)
    participant_id = participant.id
    db.session.commit()
    db.session.remove()

    participant = db.session.get(Participant, participant_id)
    participant.module_state
    with count_orm_loads() as loads:
        trial, status = trial_maker.prepare_trial(exp, participant)
    assert status == "available"
    db.session.rollback()
    return loads


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_static_trial_selection_load_does_not_grow_with_node_count(db_session):
    small = _loads_to_prepare_one_trial(SMALL)
    large = _loads_to_prepare_one_trial(LARGE)

    assert sum(large.values()) <= sum(small.values()) + 5, (
        f"Preparing one trial loaded {dict(small)} objects with {SMALL} nodes "
        f"but {dict(large)} with {LARGE} nodes."
    )
