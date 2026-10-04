from unittest.mock import MagicMock

import pytest
import sqlalchemy
from dallinger import db
from sqlalchemy import Column, String, text
from sqlalchemy.orm import object_session

from psynet.data import SQLBase
from psynet.db import (
    _set_transaction_lock_timeout,
    forbid_commits,
    read_only_transaction,
    transaction,
)
from psynet.error import ErrorRecord
from psynet.experiment import Experiment, get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Page, Response, Timeline
from psynet.utils import check_translation_is_available


class DummyTransactionModel(SQLBase):
    __tablename__ = "dummy_transaction_model"

    id = Column(String, primary_key=True)


class MutatingRenderPage(Page):
    def __init__(self):
        super().__init__(
            template_fragment_str="<p>Rendered</p>",
            time_estimate=0,
        )

    def render(self, experiment, participant, partial_mode=False):
        participant.worker_id = "mutated-during-render"
        return "<p>rendered</p>"


class ConcurrentAdvanceRenderPage(Page):
    def __init__(self, participant_id):
        super().__init__(
            template_fragment_str="<p>Rendered</p>",
            time_estimate=0,
        )
        self.participant_id = participant_id

    def render(self, experiment, participant, partial_mode=False):
        with db.engine.begin() as connection:
            connection.execute(
                text("UPDATE participant SET page_uuid = :page_uuid WHERE id = :id"),
                {"page_uuid": "advanced-during-render", "id": self.participant_id},
            )
        return "<p>rendered</p>"


def new_participant():
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id="original-worker",
        hit_id="hit",
        assignment_id="assignment",
        mode="debug",
    )
    participant.page_uuid = "render-page"
    db.session.add(participant)
    return participant


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_nested_transaction_reuses_session(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction():
        obj = DummyTransactionModel(id="nested-session")
        db.session.add(obj)
        db.session.flush()

        outer_session = object_session(obj)
        assert outer_session is db.session()

        with transaction(commit=False):
            assert object_session(obj) is outer_session
            assert db.session() is outer_session

        assert object_session(obj) is outer_session

    assert object_session(obj) is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_nested_transaction_commit_false_does_not_persist(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction(commit=False):
        obj = DummyTransactionModel(id="nested-no-commit")
        db.session.add(obj)
        db.session.flush()

        with transaction(commit=False):
            assert object_session(obj) is db.session()

    with transaction():
        assert DummyTransactionModel.query.get("nested-no-commit") is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_read_only_transaction_starts_after_write_commit(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction():
        db.session.add(DummyTransactionModel(id="rendered"))
        db.session.commit()

        with read_only_transaction() as session:
            assert not session.autoflush
            assert DummyTransactionModel.query.get("rendered") is not None

        assert not db.session().in_transaction()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_read_only_transaction_rejects_pending_orm_writes(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction():
        db.session.commit()
        with pytest.raises(RuntimeError, match="attempted to mutate ORM state"):
            with read_only_transaction():
                db.session.add(DummyTransactionModel(id="render-write"))

    assert DummyTransactionModel.query.get("render-write") is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_read_only_transaction_rejects_nested_commit(db_session):
    with transaction():
        db.session.commit()
        with read_only_transaction():
            with pytest.raises(RuntimeError, match="cannot commit"):
                db.session.commit()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_read_only_transaction_allows_no_op_assignment(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction():
        db.session.add(DummyTransactionModel(id="unchanged"))
        db.session.commit()
        with read_only_transaction():
            obj = DummyTransactionModel.query.get("unchanged")
            obj.id = "unchanged"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_forbid_commits_rejects_commits_but_allows_savepoints(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction(commit=False):
        with forbid_commits("grow_network"):
            with db.session.begin_nested():
                db.session.add(DummyTransactionModel(id="savepoint"))
            with pytest.raises(RuntimeError) as error:
                db.session.commit()

    message = str(error.value)
    assert message.startswith("grow_network called db.session.commit()")
    assert "db.session.flush()" in message
    assert "classes_and_sqlalchemy.html#saving-changes" in message


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_lucid_rejected_consent_terminates_inside_guarded_steps(
    db_session, monkeypatch
):
    """Lucid saves its termination around the API call, even inside a timeline step."""
    from psynet.end import RejectedConsentLogic
    from psynet.lucid import LucidService
    from psynet.recruiters import BaseLucidRecruiter, LucidRID

    monkeypatch.setattr(RejectedConsentLogic, "prepare_exit", lambda *args: None)
    db.session.add(LucidRID(rid="RID1"))
    db.session.commit()

    recruiter = object.__new__(BaseLucidRecruiter)
    recruiter.lucidservice = object.__new__(LucidService)
    recruiter.lucidservice.send_terminate_request = lambda rid: MagicMock(ok=True)
    recruiter.external_submit_url = lambda assignment_id: "https://lucid.example"
    experiment = MagicMock(recruiter=recruiter)
    participant = MagicMock(assignment_id="RID1", module_state=None)
    participant.recruiter = recruiter

    with transaction(commit=False):
        with pytest.raises(RuntimeError, match=r"advance_page called .*rollback"):
            with forbid_commits("Timeline.advance_page"):
                with forbid_commits("CodeBlock 'EndLogic.prepare_debrief'"):
                    RejectedConsentLogic().prepare_debrief(experiment, participant)
                db.session.add(LucidRID(rid="RID2"))
                db.session.flush()
                db.session.rollback()

    assert LucidRID.query.filter_by(rid="RID1").one().terminated_at is not None

    def commit_directly(experiment, participant):
        db.session.commit()

    recruiter.after_rejected_consent = commit_directly
    experiment.with_lucid_recruitment.return_value = False
    with transaction(commit=False):
        with pytest.raises(RuntimeError, match="prepare_debrief' called"):
            with forbid_commits("CodeBlock 'EndLogic.prepare_debrief'"):
                RejectedConsentLogic().prepare_debrief(experiment, participant)


def _skip_error_notifications(monkeypatch):
    monkeypatch.setattr(Experiment, "log_to_notifier", MagicMock())


def _translate_missing_string_live(monkeypatch):
    _skip_error_notifications(monkeypatch)
    monkeypatch.setattr("psynet.experiment.in_deployment_package", lambda: True)
    monkeypatch.setattr("psynet.deployment_info.read", lambda key: "live")
    monkeypatch.setattr(
        "psynet.utils.REGISTERED_TRANSLATIONS", {"experiment": {"de": []}}
    )
    check_translation_is_available("Not in the catalog", None, "de", "experiment")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_live_missing_translation_is_reported_without_committing(
    db_session, monkeypatch
):
    """Rendering keeps working, and a step's half-finished work stays unsaved."""
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction():
        db.session.commit()
        with read_only_transaction():
            _translate_missing_string_live(monkeypatch)

    with transaction(commit=False):
        with forbid_commits("CodeBlock 'translate'"):
            db.session.add(DummyTransactionModel(id="half-finished"))
            _translate_missing_string_live(monkeypatch)
        db.session.rollback()

    assert DummyTransactionModel.query.get("half-finished") is None
    assert ErrorRecord.query.count() == 0


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_handle_error_after_failed_flush_records_parent_ids(db_session, monkeypatch):
    _skip_error_notifications(monkeypatch)
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    participant = new_participant()
    db.session.add(DummyTransactionModel(id="duplicate"))
    db.session.commit()
    participant_id = participant.id

    db.session.add(DummyTransactionModel(id="duplicate"))
    with pytest.raises(sqlalchemy.exc.IntegrityError) as error:
        db.session.flush()
    get_experiment().handle_error(error.value, participant=participant)

    assert ErrorRecord.query.one().participant_id == participant_id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_handle_error_saves_the_record_before_notifying(db_session, monkeypatch):
    monkeypatch.setattr(
        Experiment, "log_to_notifier", MagicMock(side_effect=ConnectionError)
    )
    participant = new_participant()
    db.session.commit()

    with pytest.raises(ConnectionError):
        get_experiment().handle_error(ValueError("failed"), participant=participant)
    db.session.rollback()

    assert ErrorRecord.query.count() == 1


@pytest.mark.parametrize(
    "recruiter_class", ["BaseLabRecruiter", "BaseLucidRecruiter", "GenericRecruiter"]
)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_duration_exceeded_saves_abandonment_under_the_clock(
    db_session, recruiter_class
):
    """Dallinger's clock does not commit its session, so the recruiter must."""
    from psynet import recruiters

    participant = new_participant()
    db.session.commit()
    participant_id = participant.id
    recruiter = object.__new__(getattr(recruiters, recruiter_class))
    with db.sessions_scope():
        participant = Participant.query.get(participant_id)
        recruiter.notify_duration_exceeded([participant], reference_time=None)

    assert Participant.query.get(participant_id).status == "abandoned"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_lucid_entry_saves_new_rid_before_dallinger_discards_the_session(db_session):
    """Dallinger's POST /participant removes the session before creating the participant."""
    from psynet.recruiters import BaseLucidRecruiter, LucidRID

    recruiter = object.__new__(BaseLucidRecruiter)
    recruiter.lucidservice = MagicMock()
    recruiter.normalize_entry_information({"RID": "NEW_RID"})
    db.session.remove()

    assert LucidRID.query.filter_by(rid="NEW_RID").count() == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_commit_guard_ignores_transactions_of_other_sessions(db_session):
    db.session.commit()
    other = db.session_factory()
    try:
        with forbid_commits("CodeBlock 'other_session'"):
            other.execute(text("SELECT 1"))
            db.session.execute(text("SELECT 1"))
    finally:
        other.close()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_transaction_lock_timeout_is_scoped_locally(db_session):
    default = db.session.execute(text("SHOW lock_timeout")).scalar()
    with transaction():
        _set_transaction_lock_timeout(5)
        timeout = db.session.execute(text("SHOW lock_timeout")).scalar()
        assert timeout == "5s"

    leftover = db.session.execute(text("SHOW lock_timeout")).scalar()
    assert leftover == default


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_read_only_transaction_requires_committed_write_phase(db_session):
    DummyTransactionModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction():
        db.session.add(DummyTransactionModel(id="open-write"))
        db.session.flush()
        assert db.session().in_transaction()
        with pytest.raises(RuntimeError, match="committed write phase"):
            with read_only_transaction():
                pass


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_full_timeline_render_rejects_orm_mutation(db_session):
    participant = new_participant()
    db_session.flush()
    participant_id = participant.id
    unique_id = participant.unique_id
    page_uuid = participant.page_uuid
    experiment = get_experiment()
    db_session.commit()

    with pytest.raises(RuntimeError, match="attempted to mutate ORM state"):
        Experiment._render_timeline_page_read_only(
            experiment=experiment,
            participant_id=participant_id,
            unique_id=unique_id,
            page_uuid=page_uuid,
            page=MutatingRenderPage(),
            mode=None,
        )

    participant = Participant.query.get(participant_id)
    assert participant.worker_id == "original-worker"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_partial_timeline_render_rejects_orm_mutation(db_session):
    participant = new_participant()
    db_session.flush()
    participant_id = participant.id
    page_uuid = participant.page_uuid
    experiment = get_experiment()
    db_session.commit()

    with pytest.raises(RuntimeError, match="attempted to mutate ORM state"):
        Experiment._render_page_read_only(
            experiment=experiment,
            participant_id=participant_id,
            page_uuid=page_uuid,
            page=MutatingRenderPage(),
            kind="fragment",
        )

    participant = Participant.query.get(participant_id)
    assert participant.worker_id == "original-worker"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_partial_timeline_render_rejects_stale_page_uuid(db_session):
    participant = new_participant()
    db_session.flush()
    participant_id = participant.id
    experiment = get_experiment()
    db_session.commit()

    fragment = Experiment._render_page_read_only(
        experiment=experiment,
        participant_id=participant_id,
        page_uuid="stale-page",
        page=MutatingRenderPage(),
        kind="fragment",
    )

    assert fragment is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_timeline_render_discards_page_advanced_during_render(db_session):
    participant = new_participant()
    db_session.flush()
    participant_id = participant.id
    page_uuid = participant.page_uuid
    experiment = get_experiment()
    db_session.commit()

    rendered = Experiment._render_page_read_only(
        experiment=experiment,
        participant_id=participant_id,
        page_uuid=page_uuid,
        page=ConcurrentAdvanceRenderPage(participant_id),
        kind="full",
    )

    assert rendered is None


class CompileTrackingPage(Page):
    def __init__(self):
        super().__init__(
            template_fragment_str="<p>Rendered</p>",
            time_estimate=0,
            label="track",
        )
        self.render_calls = 0

    def render(self, experiment, participant, partial_mode=False):
        self.render_calls += 1
        raise RuntimeError("template compiled")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_full_timeline_render_compiles_templates_json_does_not(db_session):
    """``render_pages=True`` must hit HTML render, which compiles Jinja."""
    from flask import Flask

    participant = new_participant()
    db_session.flush()
    participant_id = participant.id
    page_uuid = participant.page_uuid
    experiment = get_experiment()
    db_session.commit()
    page = CompileTrackingPage()

    with Flask(__name__).test_request_context():
        json_response = Experiment._render_page_read_only(
            experiment=experiment,
            participant_id=participant_id,
            page_uuid=page_uuid,
            page=page,
            kind="json",
        )
        assert json_response is not None
        assert page.render_calls == 0
        with pytest.raises(RuntimeError, match="template compiled"):
            Experiment._render_page_read_only(
                experiment=experiment,
                participant_id=participant_id,
                page_uuid=page_uuid,
                page=page,
                kind="full",
            )
    assert page.render_calls == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_response_write_retries_cleanly_after_commit_failure(db_session, monkeypatch):
    experiment = get_experiment()
    monkeypatch.setattr(
        experiment,
        "timeline",
        Timeline(
            InfoPage("First page", time_estimate=1),
            InfoPage("Second page", time_estimate=1),
        ),
    )
    participant = new_participant()
    experiment.timeline.advance_page(experiment, participant)
    db_session.commit()
    participant_id = participant.id
    original_page_uuid = participant.page_uuid

    real_commit = db.session.commit
    commit_attempts = 0

    def fail_first_commit():
        nonlocal commit_attempts
        commit_attempts += 1
        if commit_attempts == 1:
            raise sqlalchemy.exc.OperationalError(
                "COMMIT", {}, type("SerializationFailure", (), {"pgcode": "40001"})()
            )
        return real_commit()

    monkeypatch.setattr(db.session, "commit", fail_first_commit)

    with pytest.raises(sqlalchemy.exc.OperationalError):
        with transaction():
            experiment.process_response(
                participant_id=participant_id,
                raw_answer=None,
                blobs={},
                metadata={"time_taken": 0},
                page_uuid=original_page_uuid,
                client_ip_address="127.0.0.1",
            )

    assert Response.query.filter_by(participant_id=participant_id).count() == 0
    participant = Participant.query.get(participant_id)
    assert participant.page_uuid == original_page_uuid
    assert participant.progress == 0

    with transaction():
        result = experiment.process_response(
            participant_id=participant_id,
            raw_answer=None,
            blobs={},
            metadata={"time_taken": 0},
            page_uuid=original_page_uuid,
            client_ip_address="127.0.0.1",
        )

    assert result.payload["submission"] == "approved"
    assert Response.query.filter_by(participant_id=participant_id).count() == 1
    participant = Participant.query.get(participant_id)
    assert participant.page_uuid != original_page_uuid
    assert participant.progress > 0
