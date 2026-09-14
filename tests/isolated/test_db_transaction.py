import pytest
import sqlalchemy
from dallinger import db
from sqlalchemy import Column, String, text
from sqlalchemy.orm import object_session

from psynet.data import SQLBase
from psynet.db import (
    _set_transaction_lock_timeout,
    read_only_transaction,
    transaction,
)
from psynet.experiment import Experiment, get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Page, Response, Timeline


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
