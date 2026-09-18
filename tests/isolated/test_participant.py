import logging

import pytest
from dallinger import db

from psynet.bot import Bot, BotDriver
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import SimpleSyncGroup
from psynet.trial.main import GenericTrialNode, Trial


def _add_incomplete_trial(
    trial_class,
    launched_experiment,
    node,
    participant,
    *,
    propagate_failure=False,
):
    incomplete = trial_class(
        experiment=launched_experiment,
        node=node,
        participant=participant,
        propagate_failure=propagate_failure,
        is_repeat_trial=False,
    )
    db.session.add(incomplete)
    db.session.commit()
    assert not incomplete.complete
    return incomplete


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestParticipantFailure:
    @pytest.fixture
    def participant(self, launched_experiment):
        return Bot()

    @pytest.fixture
    def trial(self, launched_experiment, trial_class, node, participant):
        trial = trial_class(
            experiment=launched_experiment,
            node=node,
            participant=participant,
            propagate_failure=False,
            is_repeat_trial=False,
        )
        db.session.add(trial)
        db.session.commit()
        return trial

    @pytest.fixture
    def trial_maker(self, experiment_module):
        maker = experiment_module.trial_maker
        original = maker.fail_trials_on_participant_performance_check
        yield maker
        maker.fail_trials_on_participant_performance_check = original

    def test_exit_fails_incomplete_and_preserves_completed(
        self, participant, trial, trial_class, node, launched_experiment
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )

        participant.fail("premature_exit")

        assert participant.failed
        assert participant.pending_redirect == "unsuccessful_end"
        assert not trial.failed
        assert incomplete.failed

    def test_complete_unfinalized_trial_survives_participant_fail(
        self, participant, trial
    ):
        trial.complete = True
        trial.finalized = False
        db.session.commit()

        participant.fail("premature_exit")

        assert trial.complete
        assert not trial.finalized
        assert not trial.failed

    def test_incomplete_cue_trial_fails_without_trial_maker(
        self, participant, trial_class, launched_experiment
    ):
        node = GenericTrialNode("cue_module", launched_experiment)
        db.session.add(node)
        incomplete = trial_class(
            experiment=launched_experiment,
            node=node,
            participant=participant,
            propagate_failure=False,
            is_repeat_trial=False,
            definition={"animal": "cats"},
        )
        db.session.add(incomplete)
        db.session.commit()
        assert incomplete.trial_maker_id is None

        original_routines = launched_experiment.participant_fail_routines
        launched_experiment.participant_fail_routines = []
        try:
            participant.fail("premature_exit")
        finally:
            launched_experiment.participant_fail_routines = original_routines

        assert incomplete.failed

    def test_default_static_policy_fails_completed_and_incomplete(
        self, participant, trial, trial_class, node, launched_experiment, trial_maker
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )

        assert trial_maker.fail_trials_on_participant_performance_check

        participant.fail("performance_check")

        assert participant.failed
        assert trial.failed
        assert incomplete.failed

    def test_performance_check_can_preserve_completed_trials(
        self, participant, trial, trial_class, node, launched_experiment, trial_maker
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )
        trial_maker.fail_trials_on_participant_performance_check = False

        participant.fail("performance_check")

        assert participant.failed
        assert not trial.failed
        assert incomplete.failed

    @pytest.mark.parametrize(
        "event",
        ["assignment_returned", "assignment_abandoned", "assignment_reassigned"],
    )
    def test_recruiter_exit_fails_incomplete_and_preserves_completed(
        self, launched_experiment, participant, trial, trial_class, node, event
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )

        getattr(launched_experiment, event)(participant)

        assert participant.failed
        assert "premature_exit" in participant.failure_tags
        assert event in participant.failure_tags
        assert not trial.failed
        assert incomplete.failed

    def test_arbitrary_failure_fails_incomplete_but_preserves_completed(
        self, participant, trial, trial_class, node, launched_experiment
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )

        participant.fail("simulated_failure")

        assert participant.failed
        assert not trial.failed
        assert incomplete.failed

    def test_already_failed_return_records_cause_without_premature_exit(
        self, launched_experiment, participant, trial, trial_maker
    ):
        trial.complete = True
        db.session.commit()
        trial_maker.fail_trials_on_participant_performance_check = False

        participant.fail("performance_check")
        assert participant.failed
        assert not trial.failed

        launched_experiment.assignment_returned(participant)

        assert "assignment_returned" in participant.failure_tags
        assert "premature_exit" not in participant.failure_tags
        assert not trial.failed

    def test_already_complete_return_is_noop(
        self, launched_experiment, participant, trial, trial_class, node
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )
        participant.complete = True
        db.session.commit()

        launched_experiment.assignment_returned(participant)

        assert participant.complete
        assert not participant.failed
        assert "assignment_returned" not in participant.failure_tags
        assert "premature_exit" not in participant.failure_tags
        assert not trial.failed
        assert not incomplete.failed
        assert participant.pending_redirect is None

    def test_fail_can_fail_completed_participant(
        self, launched_experiment, participant, trial
    ):
        trial.complete = True
        participant.complete = True
        db.session.commit()

        participant.fail("post_hoc")

        assert participant.failed
        assert participant.complete
        assert not trial.failed
        assert participant.pending_redirect is None

    def test_experiment_fail_participant_uses_psynet_contract(
        self, launched_experiment, participant, trial, trial_class, node
    ):
        trial.complete = True
        db.session.commit()
        incomplete = _add_incomplete_trial(
            trial_class, launched_experiment, node, participant
        )

        launched_experiment.fail_participant(participant)

        assert participant.failed
        assert participant.pending_redirect == "unsuccessful_end"
        assert not trial.failed
        assert incomplete.failed
        assert not node.failed

    @pytest.mark.parametrize("hook", ["data_check_failed", "attention_check_failed"])
    def test_dallinger_submission_check_hooks_warn_and_do_not_fail(
        self, launched_experiment, participant, trial, caplog, hook
    ):
        trial.complete = True
        db.session.commit()

        with caplog.at_level(logging.WARNING):
            getattr(launched_experiment, hook)(participant)

        assert not participant.failed
        assert not trial.failed
        assert not trial.node.failed
        assert "performance_check" in caplog.text
        assert hook.replace("_failed", "") in caplog.text

    def test_finalize_trial_skips_when_participant_already_failed(
        self, launched_experiment, participant, trial
    ):
        participant.current_trial = trial
        participant.answer = "Very much"
        participant.fail("premature_exit")
        db.session.commit()

        Trial._finalize_trial().function(
            participant=participant, experiment=launched_experiment
        )

        assert trial.failed
        assert not trial.complete

    def test_finalize_trial_skips_when_failed_without_current_trial(
        self, launched_experiment, participant
    ):
        participant.current_trial = None
        participant.fail("premature_exit")
        db.session.commit()

        Trial._finalize_trial().function(
            participant=participant, experiment=launched_experiment
        )

        assert participant.failed

    def test_response_timeout_submit_still_records_answer(self, launched_experiment):
        bot = BotDriver()
        assert bot.current_page_label == "animal_trial"

        trial = Trial.query.filter_by(participant_id=bot.id, complete=False).one()
        trial.fail(reason="response_timeout")
        db.session.commit()

        bot.take_page()
        bot._fetch_status()
        db.session.refresh(trial)
        participant = Participant.query.get(bot.id)

        assert trial.failed
        assert trial.complete
        assert trial.answer == "Very much"
        assert not participant.failed
        assert bot.is_working

    def test_participant_fail_while_trial_open_does_not_complete_on_submit(
        self, launched_experiment
    ):
        bot = BotDriver()
        trial = Trial.query.filter_by(participant_id=bot.id, complete=False).one()
        participant = Participant.query.get(bot.id)
        participant.fail("premature_exit")
        db.session.commit()

        bot.take_page()
        db.session.refresh(trial)
        db.session.refresh(participant)

        assert trial.failed
        assert not trial.complete
        assert participant.failed

    def test_assignment_returned_can_fail_sync_group_partners(
        self, launched_experiment, participant
    ):
        partner = Bot()
        group = SimpleSyncGroup(
            group_type="main",
            initial_group_size=2,
            max_group_size=2,
            min_group_size=2,
            n_active_participants=2,
            accepts_top_ups=False,
        )
        db.session.add(group)
        group.add_participant(participant)
        group.add_participant(partner)
        group.leader = participant
        db.session.commit()

        launched_experiment.assignment_returned(participant)
        db.session.commit()

        assert participant.failed
        assert partner.failed
        assert "sync group below minimum size" in partner.failure_tags
        assert group.n_active_participants == 0
        assert partner not in group.active_participants
