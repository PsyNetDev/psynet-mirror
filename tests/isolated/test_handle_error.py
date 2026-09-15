import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from dallinger import db

from psynet.error import ErrorRecord
from psynet.exit import (
    EarlyExitConfirmation,
    ErrorRecoveryPresentation,
    ExitContext,
    ExitPath,
    ExitPlan,
    ExitPlanStatus,
    PaymentState,
)
from psynet.experiment import Experiment
from psynet.process import WorkerAsyncProcess
from psynet.pytest_psynet import path_to_test_experiment
from psynet.recruiters import DevLucidRecruiter


def task():
    raise ValueError("process failed")


def exit_confirmation():
    return EarlyExitConfirmation("Leave?", "Saved.", "Leave", "Cancel")


def test_error_page_prepares_automatic_recovery_even_when_voluntary_leave_is_off():
    from flask import Flask

    participant = SimpleNamespace(
        id=42,
        hit_id="study-1",
        assignment_id="assignment-1",
        worker_id="worker-1",
        complete=False,
        failed=False,
        early_exited=False,
        exit_plan=None,
        fail=MagicMock(),
    )
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    experiment.plan_exit.return_value = plan
    presentation = MagicMock()
    recruiter = MagicMock(show_early_exit_button=False)
    recruiter.error_page_presentation.return_value = presentation
    recruiter.shows_error_recovery_page.return_value = True

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.side_effect = {
            "show_early_exit_button": False,
            "contact_email_on_error": "researcher@example.test",
        }.get
        Experiment.error_page(
            participant=participant,
            recruiter=recruiter,
        )

    assert participant.exit_plan == plan.to_dict()
    assert render.call_args.kwargs["automatic_exit_offer_id"] == plan.plan_id
    assert render.call_args.kwargs["error_page_presentation"] is presentation
    recruiter.prepare_error_recovery.assert_called_once_with(participant)
    experiment.plan_exit.assert_called_once_with(
        participant, ExitContext.ERROR_RECOVERY
    )
    participant.fail.assert_called_once_with("error_recovery", redirect_to_end=False)
    recruiter.error_page_presentation.assert_called_once_with(
        participant=participant,
        plan=plan,
        assignment_id="assignment-1",
        external_submit_url=None,
        contact_address="researcher@example.test",
    )


def test_render_error_page_does_not_change_recovery_state():
    from flask import Flask

    participant = SimpleNamespace(
        id=42,
        assignment_id="assignment-1",
        exit_plan={"unchanged": True},
        fail=MagicMock(),
    )
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    )
    recruiter = MagicMock()

    with (
        Flask(__name__).test_request_context("/error-page?participant_id=42"),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ),
    ):
        config.return_value.get.return_value = "researcher@example.test"
        response = Experiment._render_error_page(
            participant=participant,
            plan=plan,
            recruiter=recruiter,
            error_text=None,
            external_submit_url=None,
            locale="en",
        )

    assert response.status_code == 200
    assert participant.exit_plan == {"unchanged": True}
    participant.fail.assert_not_called()
    recruiter.prepare_error_recovery.assert_not_called()


def test_a_get_reload_of_the_error_page_replays_the_executed_recovery():
    from flask import Flask

    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    ).mark_committed()
    participant = SimpleNamespace(
        id=42,
        hit_id="study-1",
        assignment_id="assignment-1",
        worker_id="worker-1",
        complete=False,
        failed=True,
        early_exited=True,
        exit_plan=plan.to_dict(),
        fail=MagicMock(),
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    presentation = MagicMock()
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = presentation
    recruiter.shows_error_recovery_page.return_value = True

    with (
        Flask(__name__).test_request_context("/error-page?participant_id=42"),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        Experiment.error_page(participant=participant, recruiter=recruiter)

    assert render.call_args.kwargs["automatic_exit_offer_id"] is None
    assert render.call_args.kwargs["error_page_presentation"] is presentation
    recruiter.prepare_error_recovery.assert_not_called()
    participant.fail.assert_not_called()
    recruiter.error_page_presentation.assert_called_once_with(
        participant=participant,
        plan=plan,
        assignment_id="assignment-1",
        external_submit_url=None,
        contact_address="researcher@example.test",
    )
    experiment.plan_exit.assert_not_called()


def test_error_page_redirects_generic_tracked_recovery_to_timeline():
    from flask import Flask

    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    ).mark_committed()
    participant = SimpleNamespace(
        id=42,
        unique_id="worker-1:assignment-1",
        hit_id="study-1",
        assignment_id="assignment-1",
        worker_id="worker-1",
        complete=False,
        failed=True,
        early_exited=True,
        exit_plan=plan.to_dict(),
        fail=MagicMock(),
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    recruiter = MagicMock()
    recruiter.shows_error_recovery_page.return_value = False

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        response = Experiment.error_page(participant=participant, recruiter=recruiter)

    assert response.status_code in (301, 302)
    assert "/timeline?unique_id=worker-1:assignment-1" in response.location
    render.assert_not_called()
    recruiter.prepare_error_recovery.assert_not_called()
    recruiter.error_page_presentation.assert_not_called()
    experiment.plan_exit.assert_not_called()


def test_error_page_finalizes_skipped_recovery_without_a_unique_id():
    from flask import Flask

    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    ).mark_committed()
    participant = SimpleNamespace(
        id=42,
        unique_id=None,
        hit_id="study-1",
        assignment_id="assignment-1",
        worker_id="worker-1",
        complete=False,
        failed=True,
        early_exited=True,
        exit_plan=plan.to_dict(),
        fail=MagicMock(),
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    recruiter = MagicMock()
    recruiter.shows_error_recovery_page.return_value = False

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
        patch.object(Experiment, "_ensure_worker_complete") as finalize,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        response = Experiment.error_page(participant=participant, recruiter=recruiter)

    assert response.status_code == 200
    finalize.assert_called_once_with(experiment, participant)
    render.assert_called_once()
    recruiter.prepare_error_recovery.assert_not_called()
    recruiter.error_page_presentation.assert_called_once()
    experiment.plan_exit.assert_not_called()


def test_prepare_commits_with_the_policy_recruiter():
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    )
    participant = SimpleNamespace(
        id=42,
        complete=False,
        failed=True,
        early_exited=False,
        exit_plan=plan.to_dict(),
        fail=MagicMock(),
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    policy_recruiter = MagicMock()
    policy_recruiter.shows_error_recovery_page.return_value = False

    result = Experiment._prepare_error_recovery_plan(
        experiment, policy_recruiter, participant
    )

    assert result.status is ExitPlanStatus.COMMITTED
    assert result.plan_id == plan.plan_id
    policy_recruiter.execute_early_exit_plan.assert_called_once()
    executed_plan = policy_recruiter.execute_early_exit_plan.call_args.args[2]
    assert executed_plan.plan_id == plan.plan_id
    assert executed_plan.status is ExitPlanStatus.PREPARED
    experiment.recruiter.execute_early_exit_plan.assert_not_called()


def test_a_get_reload_reuses_the_prepared_error_recovery_plan():
    from flask import Flask

    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    )
    participant = SimpleNamespace(
        id=42,
        hit_id="study-1",
        assignment_id="assignment-1",
        worker_id="worker-1",
        complete=False,
        failed=True,
        early_exited=False,
        exit_plan=plan.to_dict(),
        fail=MagicMock(),
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = MagicMock()
    recruiter.shows_error_recovery_page.return_value = True

    with (
        Flask(__name__).test_request_context("/error-page?participant_id=42"),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        Experiment.error_page(participant=participant, recruiter=recruiter)

    assert participant.exit_plan == plan.to_dict()
    assert render.call_args.kwargs["automatic_exit_offer_id"] == plan.plan_id
    recruiter.prepare_error_recovery.assert_not_called()
    experiment.plan_exit.assert_not_called()
    participant.fail.assert_not_called()


def test_error_page_presents_an_executed_voluntary_plan_instead_of_untracked_copy():
    from flask import Flask

    plan = ExitPlan.create(
        context=ExitContext.VOLUNTARY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
        confirmation=exit_confirmation(),
    ).mark_committed()
    participant = SimpleNamespace(
        id=42,
        hit_id="study-1",
        assignment_id="assignment-1",
        worker_id="worker-1",
        complete=False,
        failed=True,
        early_exited=True,
        exit_plan=plan.to_dict(),
        fail=MagicMock(),
    )
    experiment = MagicMock()
    experiment.timeline.participant_is_in_end_logic.return_value = False
    presentation = MagicMock()
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = presentation

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        Experiment.error_page(participant=participant, recruiter=recruiter)

    assert render.call_args.kwargs["automatic_exit_offer_id"] is None
    recruiter.prepare_error_recovery.assert_not_called()
    experiment.plan_exit.assert_not_called()
    recruiter.error_page_presentation.assert_called_once_with(
        participant=participant,
        plan=plan,
        assignment_id="assignment-1",
        external_submit_url=None,
        contact_address="researcher@example.test",
    )


def _handoff_presentation():
    return ErrorRecoveryPresentation(
        message="We will pay you for your progress.",
        action_instruction="Select Submit to Prolific to complete your submission.",
        failure_message="We could not send your submission.",
        button_label="Submit to Prolific",
        action_post_url="/prolific-submission-listener",
        action_post_data={"assignmentId": "assignment-1", "participantId": "42"},
    )


def test_render_error_page_keeps_handoff_while_recovery_is_prepared():
    from flask import Flask

    presentation = _handoff_presentation()
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = presentation
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    )

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        Experiment._render_error_page(
            participant=SimpleNamespace(assignment_id="assignment-1"),
            plan=plan,
            recruiter=recruiter,
            error_text=None,
            external_submit_url=None,
            locale="en",
        )

    rendered = render.call_args.kwargs["error_page_presentation"]
    assert rendered is presentation
    assert rendered.button_label == "Submit to Prolific"
    assert rendered.action_post_url == "/prolific-submission-listener"
    assert render.call_args.kwargs["automatic_exit_offer_id"] == plan.plan_id


def test_render_error_page_disarms_handoff_on_a_committed_voluntary_plan():
    from flask import Flask

    presentation = _handoff_presentation()
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = presentation
    plan = ExitPlan.create(
        context=ExitContext.VOLUNTARY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
        confirmation=exit_confirmation(),
    ).mark_committed()

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        Experiment._render_error_page(
            participant=SimpleNamespace(assignment_id="assignment-1"),
            plan=plan,
            recruiter=recruiter,
            error_text=None,
            external_submit_url=None,
            locale="en",
        )

    rendered = render.call_args.kwargs["error_page_presentation"]
    assert rendered.button_label is None
    assert rendered.action_post_url is None
    assert rendered.action_instruction is None
    assert rendered.message == "We will pay you for your progress."
    assert render.call_args.kwargs["automatic_exit_offer_id"] is None


def test_render_error_page_disarms_handoff_after_skip_page_commit():
    from flask import Flask

    presentation = ErrorRecoveryPresentation(
        message="Something went wrong.",
        failure_message="The session failed.",
        button_label="Continue",
        destination_url="/custom-exit",
    )
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = presentation
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
    ).mark_committed()

    with (
        Flask(__name__).test_request_context("/error-page"),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        Experiment._render_error_page(
            participant=SimpleNamespace(assignment_id="assignment-1"),
            plan=plan,
            recruiter=recruiter,
            error_text=None,
            external_submit_url=None,
            locale="en",
        )

    rendered = render.call_args.kwargs["error_page_presentation"]
    assert rendered.button_label is None
    assert rendered.destination_url is None
    assert rendered.message == "Something went wrong."
    assert render.call_args.kwargs["automatic_exit_offer_id"] is None


def test_fail_participant_on_error_records_the_exception_without_failing():
    participant = SimpleNamespace(failure_tags=[], fail=MagicMock())

    Experiment.fail_participant_on_error(participant, ValueError("boom"))

    assert participant.failure_tags == ["ValueError"]
    participant.fail.assert_not_called()


def test_fatal_response_failure_returns_json_and_prepares_tracked_recovery():
    participant = SimpleNamespace(
        id=42,
        page_uuid="page-1",
        current_trial=None,
        client_ip_address=None,
    )
    event = MagicMock()
    event.process_response.side_effect = ValueError("boom")
    experiment = MagicMock()
    experiment.HandledError = Experiment.HandledError
    handled = Experiment.HandledError(participant_id=42)
    experiment.handle_error.return_value = handled
    query = experiment._participant_request_query.return_value
    query.with_for_update.return_value.populate_existing.return_value.get.return_value = participant
    experiment.timeline.get_current_elt.return_value = event

    with (
        patch("psynet.experiment.get_translator", return_value=lambda *args: args[-1]),
        patch(
            "psynet.experiment.error_response", return_value="json error"
        ) as error_response,
    ):
        result = Experiment.process_response(
            experiment,
            participant_id=42,
            raw_answer="answer",
            blobs={},
            metadata={},
            page_uuid="page-1",
            client_ip_address="127.0.0.1",
        )

    assert result == "json error"
    error_response.assert_called_once_with(
        error_text="There was an error processing this response.",
        status=500,
        simple=True,
    )
    experiment.handle_error.assert_called_once()
    experiment._prepare_tracked_fatal_recovery.assert_called_once_with(
        handled,
        event.process_response.side_effect,
    )


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_untracked_error_page_uses_the_same_structured_recruiter_hook(method):
    from flask import Flask

    presentation = MagicMock()
    recruiter = MagicMock()
    recruiter.error_page_presentation.return_value = presentation
    experiment = SimpleNamespace(recruiter=recruiter)

    app = Flask(__name__)
    if method == "GET":
        context = app.test_request_context("/error-page?assignment_id=assignment-1")
    else:
        context = app.test_request_context(
            "/error-page",
            method="POST",
            data={"assignment_id": "assignment-1"},
        )

    with (
        context,
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch("psynet.experiment.get_config") as config,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        config.return_value.get.return_value = "researcher@example.test"
        response = Experiment.error_page()

    assert render.call_args.kwargs["automatic_exit_offer_id"] is None
    assert render.call_args.kwargs["error_page_presentation"] is presentation
    assert response.status_code == 200
    # A cached copy would keep claiming the plan has not run yet.
    assert response.headers["Cache-Control"] == "no-store"
    recruiter.error_page_presentation.assert_called_once_with(
        participant=None,
        plan=None,
        assignment_id="assignment-1",
        external_submit_url=None,
        contact_address="researcher@example.test",
    )


def test_error_page_route_ignores_enumerable_participant_id():
    """``participant_id`` is not session authority for /error-page."""
    from flask import Flask

    with (
        Flask(__name__).test_request_context("/error-page?participant_id=42"),
        patch.object(Experiment, "error_page", return_value="error page") as error_page,
        patch("psynet.experiment.Participant") as participant_model,
    ):
        assert Experiment.render_error() == "error page"
        participant_model.query.filter_by.assert_not_called()

    error_page.assert_called_once_with()


def test_error_page_route_redirects_legacy_unique_id_to_timeline():
    from flask import Flask

    with Flask(__name__).test_request_context(
        "/error-page?unique_id=worker-1:assignment-1"
    ):
        response = Experiment.render_error()

    assert response.status_code in (301, 302)
    assert response.location.endswith("/timeline?unique_id=worker-1%3Aassignment-1")


@pytest.mark.parametrize("participant_id", ["999", "not-a-participant"])
def test_error_page_route_survives_a_url_naming_no_known_participant(participant_id):
    """Legacy participant_id URLs stay untracked instead of mutating anyone."""
    from flask import Flask

    with (
        Flask(__name__).test_request_context(
            f"/error-page?participant_id={participant_id}"
        ),
        patch.object(Experiment, "error_page", return_value="error page") as error_page,
    ):
        assert Experiment.render_error() == "error page"

    error_page.assert_called_once_with()


def test_handled_error_page_recovers_participant_and_uses_recruiter_policy():
    participant = SimpleNamespace(assignment_id="assignment-1")
    recruiter = MagicMock()
    recruiter.external_submit_url.return_value = "https://example.test/submit"
    experiment = SimpleNamespace(recruiter=recruiter)
    handled_error = Experiment.HandledError(participant_id=42)

    with (
        patch.object(
            Experiment,
            "get_participant_from_participant_id",
            return_value=participant,
        ) as get_participant,
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch.object(Experiment, "error_page", return_value="response") as error_page,
    ):
        assert handled_error.error_page() == "response"

    get_participant.assert_called_once_with(42)
    error_page.assert_called_once_with(participant=participant, recruiter=recruiter)


def test_handled_error_page_delegates_lucid_recovery():
    participant = SimpleNamespace(assignment_id="rid-1")
    recruiter = MagicMock(spec=DevLucidRecruiter)
    recruiter.external_submit_url.return_value = "https://example.test/terminate"
    experiment = SimpleNamespace(recruiter=recruiter)

    with (
        patch.object(
            Experiment,
            "get_participant_from_participant_id",
            return_value=participant,
        ),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch.object(Experiment, "error_page", return_value="response") as error_page,
    ):
        assert Experiment.HandledError(participant_id=42).error_page() == "response"

    error_page.assert_called_once_with(participant=participant, recruiter=recruiter)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_handle_error_rollback_and_record(db_session, launched_experiment, trial):
    trial_id = trial.id
    node_id = trial.node.id

    trial.answer = "original"
    db.session.commit()

    try:
        trial.answer = "new"
        raise ValueError("test error")
    except ValueError as e:
        launched_experiment.handle_error(e, trial=trial)

    db.session.refresh(trial)

    # Check that the trial is rolled back to its original state
    assert trial.answer == "original"

    error_record = ErrorRecord.query.one()
    assert error_record.trial_id == trial_id
    assert error_record.node_id == node_id
    assert error_record.kind == "ValueError"
    assert error_record.message == "test error"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_handle_error_async_process(db_session, launched_experiment, trial):
    process = WorkerAsyncProcess(function=task, trial=trial)
    db.session.commit()

    time.sleep(1)

    assert process.failed

    error_record = ErrorRecord.query.one()
    assert error_record.process_id == process.id
    assert error_record.trial_id == trial.id
