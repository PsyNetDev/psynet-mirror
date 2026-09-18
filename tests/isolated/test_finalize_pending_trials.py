import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker
from psynet.trial.main import Trial


class FinalizeBackstopTrial(ChainTrial):
    time_estimate = 1

    def make_definition(self, experiment, participant):
        return self.node.definition

    def on_finalized(self):
        # Skip the chain growth fast-path; this test only covers finalization.
        Trial.on_finalized(self)


class FinalizeBackstopNode(ChainNode):
    def create_initial_seed(self, experiment, participant):
        return {"x": 0}

    def summarize_trials(self, trials, experiment, participant):
        return {"x": trials[0].answer}

    def create_definition_from_seed(self, seed, experiment, participant):
        return seed


@pytest.fixture
def participant(db_session):
    exp = get_experiment()
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
    return participant


def _chain_trial_maker():
    return ChainTrialMaker(
        id_="finalize_backstop",
        node_class=FinalizeBackstopNode,
        trial_class=FinalizeBackstopTrial,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_experiment=1,
        max_nodes_per_chain=2,
        trials_per_node=1,
        recruit_mode="n_trials",
    )


def _create_network(trial_maker, experiment):
    start_node = trial_maker.node_class(definition={"x": 0})
    network = ChainNetwork(
        trial_maker_id=trial_maker.id,
        start_node=start_node,
        experiment=experiment,
        chain_type=trial_maker.chain_type,
        trials_per_node=trial_maker.trials_per_node,
        target_n_nodes=trial_maker.max_nodes_per_chain,
    )
    db.session.add(network)
    db.session.flush()
    return network


def _add_complete_unfinalized_trial(node, participant, **kwargs):
    trial = FinalizeBackstopTrial(
        experiment=get_experiment(),
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    trial.finalized = False
    for key, value in kwargs.items():
        setattr(trial, key, value)
    db.session.add(trial)
    db.session.flush()
    return trial


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_recovers_missed_callback(db_session, participant):
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)
    db.session.commit()

    assert trial.finalized is False
    finalized_count = Trial.finalize_pending_trials()
    db.session.commit()

    assert finalized_count == 1
    assert trial.finalized is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_skips_blocked_trials(db_session, participant):
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(
        network.head,
        participant,
        async_post_trial_requested=True,
        async_post_trial_complete=False,
    )
    db.session.commit()

    assert Trial.get_trials_ready_to_finalize() == []
    assert Trial.finalize_pending_trials() == 0
    assert trial.finalized is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_skips_asset_deposit_pending(
    db_session, participant, tmp_path
):
    from psynet.asset import ExperimentAsset

    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)

    asset_path = tmp_path / "pending.txt"
    asset_path.write_text("pending")
    asset = ExperimentAsset(
        local_key="pending",
        input_path=str(asset_path),
        parent=trial,
    )
    db.session.add(asset)
    trial.assets["pending"] = asset
    db.session.commit()

    assert asset.trial_id == trial.id
    assert asset.deposited is False
    assert trial.asset_deposit_pending is True
    assert Trial.get_trials_ready_to_finalize() == []
    assert Trial.finalize_pending_trials() == 0
    assert trial.finalized is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_failed_async_blocks_finalization_even_if_not_pending(db_session, participant):
    """Failed async is not 'pending' but must still block finalize."""
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(
        network.head,
        participant,
        async_post_trial_requested=True,
        async_post_trial_complete=False,
        async_post_trial_failed=True,
    )
    db.session.commit()

    assert trial.async_post_trial_pending is False
    assert trial.async_post_trial_blocks_finalization is True
    assert Trial.get_trials_ready_to_finalize() == []
    trial.check_if_can_mark_as_finalized()
    assert trial.finalized is False


class FailingAsyncTrial(FinalizeBackstopTrial):
    run_async_post_trial = True

    def async_post_trial(self):
        raise RuntimeError("intentional async_post_trial failure")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_call_async_post_trial_failure_fails_trial(db_session, participant):
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = FailingAsyncTrial(
        experiment=exp,
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    trial.finalized = False
    trial.async_post_trial_requested = True
    db.session.add(trial)
    db.session.commit()

    with pytest.raises(RuntimeError, match="intentional async_post_trial failure"):
        trial.call_async_post_trial()

    db.session.refresh(trial)
    assert trial.async_post_trial_failed is True
    assert trial.failed is True
    assert "async_post_trial_failed" in (trial.failed_reason or "")
    assert trial.finalized is False
    assert Trial.get_trials_ready_to_finalize() == []


class ExplodingFinalizeTrial(FinalizeBackstopTrial):
    def on_finalized(self):
        raise RuntimeError("intentional finalize backstop failure")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_isolates_per_trial_errors(
    db_session, participant, monkeypatch
):
    # handle_error -> report_error -> notifier needs a base URL; skip notifier I/O.
    monkeypatch.setattr(
        type(get_experiment()),
        "log_to_notifier",
        classmethod(lambda cls, *args, **kwargs: None),
    )

    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    good_network = _create_network(trial_maker, exp)
    bad_network = _create_network(trial_maker, exp)

    good_trial = _add_complete_unfinalized_trial(good_network.head, participant)
    bad_trial = ExplodingFinalizeTrial(
        experiment=exp,
        node=bad_network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    bad_trial.answer = 1
    bad_trial.complete = True
    bad_trial.finalized = False
    db.session.add(bad_trial)
    db.session.commit()

    Trial.finalize_pending_trials()
    db.session.commit()

    db.session.refresh(good_trial)
    db.session.refresh(bad_trial)
    assert bad_trial.failed is True
    assert "finalize_backstop_error" in (bad_trial.failed_reason or "")
    # handle_error rolls back uncommitted successes, so the good trial is
    # retried next poll.
    assert good_trial.finalized is False
    assert Trial.finalize_pending_trials() == 1
    db.session.commit()
    db.session.refresh(good_trial)
    assert good_trial.finalized is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_commits_each_failed_trial(
    db_session, participant, monkeypatch
):
    """Two bad trials in one poll must both stay failed (not O(k) retries)."""
    monkeypatch.setattr(
        type(get_experiment()),
        "log_to_notifier",
        classmethod(lambda cls, *args, **kwargs: None),
    )

    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    first_network = _create_network(trial_maker, exp)
    second_network = _create_network(trial_maker, exp)

    first_bad = ExplodingFinalizeTrial(
        experiment=exp,
        node=first_network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    first_bad.answer = 1
    first_bad.complete = True
    first_bad.finalized = False
    second_bad = ExplodingFinalizeTrial(
        experiment=exp,
        node=second_network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    second_bad.answer = 1
    second_bad.complete = True
    second_bad.finalized = False
    db.session.add_all([first_bad, second_bad])
    db.session.commit()

    Trial.finalize_pending_trials()
    db.session.commit()

    db.session.refresh(first_bad)
    db.session.refresh(second_bad)
    assert first_bad.failed is True
    assert second_bad.failed is True
    assert Trial.get_trials_ready_to_finalize() == []
    assert Trial.finalize_pending_trials() == 0
