import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


class DummyTrial(StaticTrial):
    time_estimate = 1

    def show_trial(self, experiment, participant):
        pass


def _worker_id():
    return str(uuid.uuid4())


def _make_participant(experiment, *, complete=False, failed=False, status="working"):
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=_worker_id(),
        hit_id=_worker_id(),
        assignment_id=_worker_id(),
        mode="debug",
    )
    participant.status = status
    participant.complete = complete
    participant.failed = failed
    db.session.add(participant)
    db.session.commit()
    return participant


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("timeline")],
    indirect=True,
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestNParticipantsCompletionModes:
    def test_n_participants_completion_modes(self, db_session):
        experiment = get_experiment()
        trial_maker = StaticTrialMaker(
            id_="quota",
            trial_class=DummyTrial,
            nodes=[StaticNode(definition={"x": 1})],
            expected_trials_per_participant=1,
            target_n_participants=1,
            recruit_mode="n_participants",
        )

        finished_still_in_experiment = _make_participant(experiment)
        trial_maker.start(finished_still_in_experiment)
        trial_maker.end(finished_still_in_experiment)

        in_progress = _make_participant(experiment)
        trial_maker.start(in_progress)

        failed_inside = _make_participant(experiment, failed=True)
        trial_maker.start(failed_inside)

        dropout_after_finish = _make_participant(experiment, status="returned")
        trial_maker.start(dropout_after_finish)
        trial_maker.end(dropout_after_finish)

        failed_after_finish = _make_participant(experiment, failed=True)
        trial_maker.start(failed_after_finish)
        trial_maker.end(failed_after_finish)

        early_exited_inside = _make_participant(experiment)
        trial_maker.start(early_exited_inside)
        early_exited_inside.early_exited = True
        early_exited_inside.module_state.mark_early_exited()

        not_yet_started = _make_participant(experiment)
        assert "quota" not in not_yet_started.module_states
        db.session.commit()

        trial_maker.n_participants_completion = "experiment"
        assert trial_maker.n_complete_participants == 0
        assert trial_maker.n_working_participants == 4
        assert not trial_maker.n_participants_criterion(experiment)

        trial_maker.n_participants_completion = "trial_maker"
        assert trial_maker.n_complete_participants == 3
        assert trial_maker.n_working_participants == 2
        assert not trial_maker.n_participants_criterion(experiment)

        trial_maker.target_n_participants = 6
        assert trial_maker.n_participants_criterion(experiment)
