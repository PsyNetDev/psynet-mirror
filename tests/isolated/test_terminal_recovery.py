"""Focused contracts for tracked fatal recovery and completion backstops."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from dallinger import db
from flask import Flask

from psynet.end import ErrorRecoveryPage, RecordedSubmissionPage, SuccessfulEndLogic
from psynet.exit import ExitContext, ExitPath, ExitPlan, ExitPlanStatus, PaymentDecision
from psynet.experiment import Experiment, get_experiment
from psynet.page import ExecuteFrontEndJS, InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("timeline")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


def _make_participant(**overrides):
    experiment = get_experiment()
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    for key, value in overrides.items():
        setattr(participant, key, value)
    db.session.add(participant)
    db.session.commit()
    return participant


def test_error_page_with_participant_id_does_not_mutate_arbitrary_participant(
    db_session,
):
    """GET /error-page?participant_id=N must not fail strangers."""
    victim = _make_participant()
    victim_id = victim.id
    assert victim.failed is False
    assert victim.exit_plan is None

    with (
        Flask(__name__).test_request_context(f"/error-page?participant_id={victim_id}"),
        patch("psynet.experiment.get_experiment", return_value=get_experiment()),
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ),
    ):
        Experiment.render_error()

    db.session.remove()
    reloaded = Participant.query.get(victim_id)
    assert reloaded.failed is False
    assert reloaded.exit_plan is None


def test_fatal_response_prepares_recovery_in_the_same_request(db_session):
    """Fatal /response cleanup must not wait for a later browser GET."""
    participant = _make_participant(page_uuid="page-1")
    participant_id = participant.id

    event = MagicMock()
    event.is_timeline_hold = False
    event.process_response.side_effect = ValueError("boom")
    experiment = get_experiment()

    with (
        patch.object(
            experiment,
            "_participant_request_query",
            return_value=SimpleNamespace(
                with_for_update=lambda **kwargs: SimpleNamespace(
                    populate_existing=lambda: SimpleNamespace(
                        get=lambda _id: participant
                    )
                )
            ),
        ),
        patch.object(experiment.timeline, "get_current_elt", return_value=event),
        patch.object(Experiment, "report_error"),
        patch(
            "psynet.experiment.error_response", return_value="json error"
        ) as error_response,
    ):
        result = experiment.process_response(
            participant_id=participant_id,
            raw_answer="answer",
            blobs={},
            metadata={},
            page_uuid="page-1",
            client_ip_address="127.0.0.1",
        )

    assert result.flask_response == "json error"
    error_response.assert_called_once()

    db.session.commit()
    db.session.remove()
    after_fatal = Participant.query.get(participant_id)
    assert after_fatal.failed is True
    assert after_fatal.exit_plan is not None
    assert after_fatal.early_exited is True
    assert after_fatal.page_uuid != "page-1"
    assert ExitPlan.from_dict(after_fatal.exit_plan).status is ExitPlanStatus.COMMITTED
    assert "error_recovery" in (after_fatal.failure_tags or [])
    assert "ValueError" in (after_fatal.failure_tags or [])


def test_generic_tracked_recovery_commits_without_a_recovery_page(db_session):
    """Generic fatal recovery skips Continue/Submit, then shows the error page."""
    participant = _make_participant(page_uuid="page-1")
    experiment = get_experiment()
    plan = Experiment._prepare_error_recovery_plan(
        experiment,
        experiment.recruiter,
        participant,
    )
    db.session.commit()
    unique_id = participant.unique_id

    assert plan.status is ExitPlanStatus.COMMITTED
    assert ExitPlan.from_dict(participant.exit_plan).status is ExitPlanStatus.COMMITTED
    assert experiment.timeline.get_participant_branch(participant) != (
        "early_exit_release"
    )
    assert not isinstance(
        experiment.timeline.get_current_elt(experiment, participant),
        ErrorRecoveryPage,
    )
    assert participant.early_exited is True
    assert participant.page_uuid != "page-1"

    with (
        Flask(__name__).test_request_context(
            f"/timeline?unique_id={unique_id}",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ),
        patch.object(experiment, "participant_task_completed"),
        patch("dallinger.experiment_server.worker_events.worker_function"),
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        response = Experiment._route_timeline(experiment, participant, mode=None)

    assert response.status_code == 200
    assert render.called
    assert render.call_args.kwargs["error_page_presentation"] is not None
    assert render.call_args.kwargs["automatic_exit_offer_id"] is None
    assert participant.end_time is not None


def test_skipped_recovery_reload_keeps_the_error_page(db_session):
    """A second /timeline after skip finalize still explains the error."""
    participant = _make_participant(page_uuid="page-1")
    experiment = get_experiment()
    Experiment._prepare_error_recovery_plan(
        experiment,
        experiment.recruiter,
        participant,
    )
    db.session.commit()
    unique_id = participant.unique_id

    with (
        Flask(__name__).test_request_context(
            f"/timeline?unique_id={unique_id}",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ),
        patch.object(experiment, "participant_task_completed"),
        patch("dallinger.experiment_server.worker_events.worker_function") as worker,
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        first = Experiment._route_timeline(experiment, participant, mode=None)
        assert first.status_code == 200
        assert participant.end_time is not None
        worker_calls = worker.call_count
        second = Experiment._route_timeline(experiment, participant, mode=None)

    assert second.status_code == 200
    assert worker.call_count == worker_calls
    assert render.call_count == 2
    assert render.call_args.kwargs["automatic_exit_offer_id"] is None
    assert render.call_args.kwargs["error_page_presentation"] is not None


def test_skipped_recovery_rejects_a_later_timeline_response(db_session):
    """Skip-page recovery must not let a stale or matching /response advance."""
    participant = _make_participant(page_uuid="page-1")
    original_uuid = participant.page_uuid
    experiment = get_experiment()
    Experiment._prepare_error_recovery_plan(
        experiment,
        experiment.recruiter,
        participant,
    )
    db.session.commit()
    event = MagicMock()
    event.is_timeline_hold = False

    with (
        Flask(__name__).test_request_context("/response"),
        patch.object(
            experiment,
            "_participant_request_query",
            return_value=SimpleNamespace(
                with_for_update=lambda **kwargs: SimpleNamespace(
                    populate_existing=lambda: SimpleNamespace(
                        get=lambda _id: participant
                    )
                )
            ),
        ),
        patch.object(experiment.timeline, "get_current_elt", return_value=event),
        patch("psynet.experiment.get_translator", return_value=lambda *args: args[-1]),
    ):
        stale = experiment.process_response(
            participant_id=participant.id,
            raw_answer="answer",
            blobs={},
            metadata={},
            page_uuid=original_uuid,
            client_ip_address="127.0.0.1",
        )
        matching = experiment.process_response(
            participant_id=participant.id,
            raw_answer="answer",
            blobs={},
            metadata={},
            page_uuid=participant.page_uuid,
            client_ip_address="127.0.0.1",
        )

    event.process_response.assert_not_called()
    for result in (stale, matching):
        assert result.payload["submission"] == "rejected"
        assert "already ended" in result.payload["message"]


def test_prepare_commits_a_leftover_prepared_generic_recovery_plan(db_session):
    """A leftover prepared generic plan is committed; /timeline then shows the error."""
    participant = _make_participant(page_uuid="page-1")
    experiment = get_experiment()
    with patch.object(
        experiment.recruiter, "shows_error_recovery_page", return_value=True
    ):
        Experiment._prepare_error_recovery_plan(
            experiment,
            experiment.recruiter,
            participant,
        )
    assert ExitPlan.from_dict(participant.exit_plan).status is ExitPlanStatus.PREPARED
    assert participant.early_exited is False

    plan = Experiment._prepare_error_recovery_plan(
        experiment,
        experiment.recruiter,
        participant,
    )
    assert plan.status is ExitPlanStatus.COMMITTED
    assert participant.early_exited is True

    with (
        Flask(__name__).test_request_context(
            f"/timeline?unique_id={participant.unique_id}",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ),
        patch.object(experiment, "participant_task_completed"),
        patch("dallinger.experiment_server.worker_events.worker_function"),
        patch(
            "psynet.experiment.render_template_with_translations",
            return_value="error page",
        ) as render,
    ):
        response = Experiment._route_timeline(experiment, participant, mode=None)

    assert response.status_code == 200
    assert render.called
    assert render.call_args.kwargs["automatic_exit_offer_id"] is None


def test_commit_stored_early_exit_plan_is_idempotent(db_session):
    """The stored plan is the source of truth; a second commit is a no-op."""
    participant = _make_participant(page_uuid="page-1")
    experiment = get_experiment()
    first = Experiment._prepare_error_recovery_plan(
        experiment,
        experiment.recruiter,
        participant,
    )
    with patch.object(experiment.recruiter, "execute_early_exit_plan") as execute:
        second = Experiment._commit_stored_early_exit_plan(experiment, participant)

    assert first.status is ExitPlanStatus.COMMITTED
    assert second is not None
    assert second.status is ExitPlanStatus.COMMITTED
    assert second.plan_id == first.plan_id
    assert second.to_dict() == ExitPlan.from_dict(participant.exit_plan).to_dict()
    execute.assert_not_called()


def test_prepared_recovery_is_the_first_early_exit_release_page(db_session):
    """Recruiters that present recovery UI keep it as the first release page."""
    participant = _make_participant(page_uuid="page-1")
    experiment = get_experiment()
    with patch.object(
        experiment.recruiter, "shows_error_recovery_page", return_value=True
    ):
        Experiment._prepare_error_recovery_plan(
            experiment,
            experiment.recruiter,
            participant,
        )
        db.session.commit()
        unique_id = participant.unique_id

        assert experiment.timeline.get_participant_branch(participant) == (
            "early_exit_release"
        )
        assert isinstance(
            experiment.timeline.get_current_elt(experiment, participant),
            ErrorRecoveryPage,
        )
        assert (
            ExitPlan.from_dict(participant.exit_plan).status is ExitPlanStatus.PREPARED
        )
        assert participant.early_exited is False

        with (
            Flask(__name__).test_request_context(
                f"/timeline?unique_id={unique_id}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ),
            patch(
                "psynet.experiment.render_template_with_translations",
                return_value="stored recovery",
            ) as render,
        ):
            response = Experiment._route_timeline(experiment, participant, mode=None)

        assert response.status_code == 200
        assert render.called
        assert render.call_args.kwargs["automatic_exit_offer_id"] is not None
        assert (
            ExitPlan.from_dict(participant.exit_plan).status is ExitPlanStatus.PREPARED
        )
        assert participant.early_exited is False


def test_committed_return_for_bonus_continue_renders_payment_instructions(db_session):
    """Continue after return-for-bonus recovery must not re-render the error page."""
    participant = _make_participant(page_uuid="page-1")
    experiment = get_experiment()
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.RETURN_FOR_BONUS,
        payment=PaymentDecision("returned", 0.0, 0.60),
        currency="$",
    )
    payment_copy = (
        "Please return your submission via the Prolific interface and click Next."
    )

    def release_participant(_experiment, _participant):
        return InfoPage(payment_copy, time_estimate=0.0)

    with (
        patch.object(
            experiment.recruiter, "shows_error_recovery_page", return_value=True
        ),
        patch.object(experiment.recruiter, "plan_exit", return_value=plan),
        patch.object(experiment.recruiter, "execute_early_exit_plan"),
        patch.object(
            experiment.recruiter, "release_participant", side_effect=release_participant
        ),
    ):
        Experiment._prepare_error_recovery_plan(
            experiment,
            experiment.recruiter,
            participant,
        )
        assert isinstance(
            experiment.timeline.get_current_elt(experiment, participant),
            ErrorRecoveryPage,
        )
        committed = Experiment._commit_stored_early_exit_plan(experiment, participant)
        assert committed.status is ExitPlanStatus.COMMITTED
        Experiment._enter_early_exit_release(experiment, participant)
        current = experiment.timeline.get_current_elt(experiment, participant)
        assert not isinstance(current, ErrorRecoveryPage)
        assert payment_copy in current.plain_text
        assert not Experiment._skipped_error_recovery_should_render_error_page(
            experiment, participant
        )

        with (
            Flask(__name__).test_request_context(
                f"/timeline?unique_id={participant.unique_id}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ),
            patch.object(InfoPage, "render", return_value=payment_copy) as render,
            patch.object(Experiment, "_render_error_page") as error_page,
        ):
            response = Experiment._route_timeline(experiment, participant, mode=None)

        assert response == payment_copy
        render.assert_called_once()
        error_page.assert_not_called()


def test_prolific_screen_out_timeline_confirms_after_listener_records_submission(
    db_session,
):
    """Submit's listener runs after execute; /timeline must re-evaluate release."""
    from psynet.recruiters import PsyNetProlificRecruiterMixin

    participant = _make_participant(page_uuid="page-1", status="working")
    experiment = get_experiment()
    plan = ExitPlan.create(
        context=ExitContext.ERROR_RECOVERY,
        path=ExitPath.SCREEN_OUT,
        payment=PaymentDecision("screened_out", 0.25, 0.0),
        currency="£",
    )
    prolific = object.__new__(PsyNetProlificRecruiterMixin)

    def _identity_translator(context, message):
        return message

    with (
        patch.object(
            experiment.recruiter, "shows_error_recovery_page", return_value=True
        ),
        patch.object(experiment.recruiter, "plan_exit", return_value=plan),
        patch.object(experiment.recruiter, "execute_early_exit_plan"),
        patch.object(
            experiment.recruiter,
            "release_participant",
            prolific.release_participant,
        ),
        patch(
            "psynet.recruiters.get_translator",
            return_value=_identity_translator,
        ),
    ):
        Experiment._prepare_error_recovery_plan(
            experiment,
            experiment.recruiter,
            participant,
        )
        assert isinstance(
            experiment.timeline.get_current_elt(experiment, participant),
            ErrorRecoveryPage,
        )
        Experiment._commit_stored_early_exit_plan(experiment, participant)
        Experiment._enter_early_exit_release(experiment, participant)
        assert isinstance(
            experiment.timeline.get_current_elt(experiment, participant),
            ExecuteFrontEndJS,
        )

        participant.status = "submitted"
        current = experiment.timeline.get_current_elt(experiment, participant)
        assert type(current) is RecordedSubmissionPage
        heading, body = prolific._recorded_submission_copy()
        assert heading == "Your submission has been sent to Prolific."
        assert body == "You may close this page."
        assert "An error occurred" not in heading

        with (
            Flask(__name__).test_request_context(
                f"/timeline?unique_id={participant.unique_id}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ),
            patch.object(
                RecordedSubmissionPage, "render", return_value="sent"
            ) as render,
            patch.object(Experiment, "_render_error_page") as error_page,
        ):
            response = Experiment._route_timeline(experiment, participant, mode=None)

    assert response == "sent"
    render.assert_called_once()
    error_page.assert_not_called()


def test_complete_timeline_visit_backstops_worker_complete(db_session):
    """Complete /timeline visits must stamp end_time before recruiter exit."""
    participant = _make_participant(complete=True, end_time=None, status="working")
    unique_id = participant.unique_id
    participant_id = participant.id
    experiment = get_experiment()

    with (
        Flask(__name__).test_request_context(f"/timeline?unique_id={unique_id}"),
        patch.object(experiment, "participant_task_completed"),
        patch("dallinger.experiment_server.worker_events.worker_function"),
    ):
        response = Experiment._route_timeline(experiment, participant, mode=None)

    assert response.status_code in (301, 302)
    assert f"/recruiter-exit?participant_id={participant_id}" in response.location

    db.session.commit()
    db.session.remove()
    reloaded = Participant.query.get(participant_id)
    assert reloaded.end_time is not None
    assert reloaded.status == "submitted"


def test_complete_timeline_visit_survives_worker_complete_closing_the_session(
    db_session,
):
    """Recruiter completion may close the session before the redirect is built."""
    participant = _make_participant(complete=True, end_time=None, status="working")
    unique_id = participant.unique_id
    participant_id = participant.id
    experiment = get_experiment()

    def close_session(*args, **kwargs):
        db.session.remove()

    with (
        Flask(__name__).test_request_context(f"/timeline?unique_id={unique_id}"),
        patch.object(experiment, "participant_task_completed"),
        patch(
            "dallinger.experiment_server.worker_events.worker_function",
            side_effect=close_session,
        ),
    ):
        response = Experiment._route_timeline(experiment, participant, mode=None)

    assert response.status_code in (301, 302)
    assert f"/recruiter-exit?participant_id={participant_id}" in response.location


def test_ensure_worker_complete_is_idempotent(db_session):
    participant = _make_participant(complete=True, end_time=None, status="working")
    experiment = get_experiment()

    with (
        patch.object(experiment, "participant_task_completed"),
        patch(
            "dallinger.experiment_server.worker_events.worker_function"
        ) as worker_function,
    ):
        Experiment._ensure_worker_complete(experiment, participant)
        first_end_time = participant.end_time
        assert first_end_time is not None
        Experiment._ensure_worker_complete(experiment, participant)
        assert participant.end_time == first_end_time
        assert worker_function.call_count == 1


def test_after_debrief_sets_complete_before_worker_complete(db_session):
    """Successful end marks complete while end_time is still unset."""
    participant = _make_participant(end_time=None, status="working")
    SuccessfulEndLogic().after_debrief(get_experiment(), participant)
    assert participant.complete is True
    assert participant.end_time is None
