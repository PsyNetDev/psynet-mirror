"""Tests for transactional callbacks on :meth:`Trial.cue`."""

import uuid

import pytest
from dallinger import db
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from psynet.asset import Asset, ExternalAsset
from psynet.data import SQLBase, SQLMixin, register_table
from psynet.db import transaction
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.main import GenericTrialNode, Trial


@register_table
class CueCreationRecord(SQLBase, SQLMixin):
    __tablename__ = "cue_creation_record"

    trial_id = Column(Integer, ForeignKey("trial.id"), unique=True)
    trial = relationship(Trial, foreign_keys=[trial_id])


class CueTrial(Trial):
    time_estimate = 1

    def show_trial(self, experiment, participant):
        raise NotImplementedError


@pytest.fixture
def participant_and_node(db_session):
    experiment = get_experiment()
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    node = GenericTrialNode("cue_callback_test", experiment)
    db.session.add_all([participant, node])
    db.session.flush()
    return experiment, participant, node


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_cue_calls_on_trial_created_with_context(
    db_session,
    participant_and_node,
    monkeypatch,
):
    experiment, participant, node = participant_and_node
    callback_calls = []
    monkeypatch.setattr(
        CueTrial,
        "get_default_parent_node",
        classmethod(lambda cls, participant, experiment: node),
    )

    def on_trial_created(trial, participant, experiment, creation_context):
        callback_calls.append((trial, participant, experiment, creation_context))
        record = CueCreationRecord()
        record.trial = trial
        db.session.add(record)

    logic = CueTrial.cue(
        definition={},
        on_trial_created=on_trial_created,
        creation_context={"snapshot_id": 12},
    )

    with transaction():
        logic[0].consume(experiment, participant)

    trial = CueTrial.query.one()
    record = CueCreationRecord.query.one()
    assert len(callback_calls) == 1
    callback_trial, callback_participant, callback_experiment, callback_context = (
        callback_calls[0]
    )
    assert isinstance(callback_trial, CueTrial)
    assert callback_participant is participant
    assert callback_experiment is experiment
    assert callback_context == {"snapshot_id": 12}
    assert record.trial == trial


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_cue_callback_failure_rolls_back_trial_and_related_records(
    db_session,
    participant_and_node,
    monkeypatch,
):
    experiment, participant, node = participant_and_node
    monkeypatch.setattr(
        CueTrial,
        "get_default_parent_node",
        classmethod(lambda cls, participant, experiment: node),
    )

    def on_trial_created(trial):
        record = CueCreationRecord()
        record.trial = trial
        db.session.add(record)
        raise RuntimeError("callback failed")

    logic = CueTrial.cue(
        definition={},
        on_trial_created=on_trial_created,
    )

    with pytest.raises(RuntimeError, match="callback failed"):
        with transaction():
            logic[0].consume(experiment, participant)

    assert CueTrial.query.count() == 0
    assert CueCreationRecord.query.count() == 0


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_cue_adds_assets_before_on_trial_created(
    db_session,
    participant_and_node,
    monkeypatch,
):
    experiment, participant, node = participant_and_node
    monkeypatch.setattr(
        CueTrial,
        "get_default_parent_node",
        classmethod(lambda cls, participant, experiment: node),
    )
    stimulus = ExternalAsset("http://example.com/example.mp3")

    def on_trial_created(trial):
        assert "stimulus" in trial.assets
        assert trial.assets["stimulus"] is stimulus
        record = CueCreationRecord()
        record.trial = trial
        db.session.add(record)

    logic = CueTrial.cue(
        definition={},
        assets={"stimulus": stimulus},
        on_trial_created=on_trial_created,
    )

    with transaction():
        logic[0].consume(experiment, participant)

    trial = CueTrial.query.one()
    assert trial.assets["stimulus"].url == "http://example.com/example.mp3"
    assert CueCreationRecord.query.one().trial == trial


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_cue_asset_callback_failure_rolls_back_trial_and_assets(
    db_session,
    participant_and_node,
    monkeypatch,
):
    experiment, participant, node = participant_and_node
    monkeypatch.setattr(
        CueTrial,
        "get_default_parent_node",
        classmethod(lambda cls, participant, experiment: node),
    )
    assets_before = Asset.query.count()

    def on_trial_created(trial):
        assert "stimulus" in trial.assets
        record = CueCreationRecord()
        record.trial = trial
        db.session.add(record)
        raise RuntimeError("callback failed")

    logic = CueTrial.cue(
        definition={},
        assets={"stimulus": ExternalAsset("http://example.com/example.mp3")},
        on_trial_created=on_trial_created,
    )

    with pytest.raises(RuntimeError, match="callback failed"):
        with transaction():
            logic[0].consume(experiment, participant)

    assert CueTrial.query.count() == 0
    assert CueCreationRecord.query.count() == 0
    assert Asset.query.count() == assets_before


def test_cue_creation_context_requires_on_trial_created():
    with pytest.raises(
        ValueError, match="creation_context requires an on_trial_created callback"
    ):
        CueTrial.cue(definition={}, creation_context={"snapshot_id": 12})
