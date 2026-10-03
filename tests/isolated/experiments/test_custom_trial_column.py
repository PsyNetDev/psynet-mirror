import shutil
import sys
import uuid

import pytest
from dallinger import db
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import deferred

from psynet.command_line import clean_sys_modules
from psynet.data import InvalidDefinitionError
from psynet.experiment import get_experiment, import_local_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.static import StaticNode, StaticTrial
from psynet.utils import working_directory

pytest_plugins = ["pytest_dallinger", "pytest_psynet"]


class FirstSiblingTrial(StaticTrial):
    time_estimate = 1
    sibling_probe = Column(String)

    def show_trial(self, experiment, participant):
        pass


class SecondSiblingTrial(StaticTrial):
    time_estimate = 1
    sibling_probe = Column(String)

    def show_trial(self, experiment, participant):
        pass


class DeferredSiblingTrial(StaticTrial):
    time_estimate = 1
    sibling_probe = deferred(Column(String))

    def show_trial(self, experiment, participant):
        pass


class ColumnOptionsTrial(StaticTrial):
    time_estimate = 1
    numeric_probe = Column(Numeric(precision=8, scale=2))
    scalar_default_probe = Column(Integer, default=1)
    callable_default_probe = Column(Integer, default=lambda: 1)
    server_default_probe = Column(Integer, server_default=text("1"))
    onupdate_probe = Column(Integer, onupdate=2)
    constrained_probe = Column(Integer, CheckConstraint("constrained_probe >= 0"))
    foreign_key_probe = Column(
        Integer, ForeignKey("participant.id", ondelete="CASCADE")
    )

    def show_trial(self, experiment, participant):
        pass


def declare_trial_class(attribute, column):
    """Declare a throwaway trial class carrying one custom column."""

    name = "".join(part.title() for part in attribute.split("_"))
    return type(f"Declared{name}Trial", (StaticTrial,), {attribute: column})


def test_experiment_with_custom_trial_column_imports_from_two_directories(tmp_path):
    """PsyNet reimports experiment.py from its staging copy during debug and deploy."""
    source = path_to_test_experiment("custom_trial_column")
    staging_copy = tmp_path / "staging_copy"
    shutil.copytree(source, staging_copy, ignore=shutil.ignore_patterns("__pycache__"))

    with working_directory(source):
        first = import_local_experiment()["module"].CustomColumnTrial

    clean_sys_modules()

    with working_directory(str(staging_copy)):
        second = import_local_experiment()["module"].CustomColumnTrial

    assert first is not second
    assert first.__table__.c.item_id is second.__table__.c.item_id
    # A callable default cannot be compared between two classes, so reuse has to
    # recognize that this is the same class being declared again.
    assert first.__table__.c.attempts is second.__table__.c.attempts


def test_sibling_trial_classes_may_declare_the_same_column():
    assert (
        FirstSiblingTrial.__table__.c.sibling_probe
        is SecondSiblingTrial.__table__.c.sibling_probe
    )


def test_deferred_custom_columns_reuse_the_inherited_column():
    assert (
        FirstSiblingTrial.__table__.c.sibling_probe
        is DeferredSiblingTrial.__table__.c.sibling_probe
    )


def test_equivalent_column_options_are_reused():
    equivalent_columns = {
        "numeric_probe": Column(Numeric(precision=8, scale=2)),
        "scalar_default_probe": Column(Integer, default=1),
        "server_default_probe": Column(Integer, server_default=text("1")),
        "onupdate_probe": Column(Integer, onupdate=2),
        "constrained_probe": Column(Integer, CheckConstraint("constrained_probe >= 0")),
        "foreign_key_probe": Column(
            Integer, ForeignKey("participant.id", ondelete="CASCADE")
        ),
    }
    equivalent = type(
        "EquivalentColumnOptionsTrial", (StaticTrial,), dict(equivalent_columns)
    )
    for attribute in equivalent_columns:
        assert getattr(ColumnOptionsTrial.__table__.c, attribute) is getattr(
            equivalent.__table__.c, attribute
        )


@pytest.mark.parametrize(
    ("attribute", "column", "match"),
    [
        ("sibling_probe", Column(Integer), "already exists as String"),
        ("sibling_probe", Column(String(200)), "length"),
        ("sibling_probe", Column(String, nullable=False), "nullable"),
        ("sibling_probe", Column(String, unique=True), "unique"),
        ("sibling_probe", Column(String, index=True), "index"),
        ("sibling_probe", Column(String, primary_key=True), "primary_key"),
        ("sibling_probe", Column(String, ForeignKey("participant.id")), "foreign-key"),
        ("numeric_probe", Column(Numeric(precision=10, scale=2)), "already exists"),
        ("scalar_default_probe", Column(Integer, default=2), "default"),
        ("server_default_probe", Column(Integer, server_default=text("2")), "default"),
        ("onupdate_probe", Column(Integer, onupdate=3), "onupdate"),
        (
            "constrained_probe",
            Column(Integer, CheckConstraint("constrained_probe > 0")),
            "constraints",
        ),
        (
            "foreign_key_probe",
            Column(Integer, ForeignKey("participant.id", ondelete="SET NULL")),
            "foreign-key",
        ),
    ],
)
def test_conflicting_column_definitions_are_rejected(attribute, column, match):
    with pytest.raises(InvalidDefinitionError, match=match):
        declare_trial_class(attribute, column)


@pytest.mark.parametrize("default", [lambda: 1, lambda: 2])
def test_callable_defaults_cannot_be_shared_between_classes(default):
    """PsyNet does not try to decide whether two functions behave alike."""
    with pytest.raises(InvalidDefinitionError, match="cannot be compared"):
        declare_trial_class("callable_default_probe", Column(Integer, default=default))


def test_import_local_experiment_does_not_put_the_experiment_directory_on_sys_path():
    experiment_dir = path_to_test_experiment("custom_trial_column")
    with working_directory(experiment_dir):
        before = list(sys.path)
        import_local_experiment()
        assert sys.path == before


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("custom_trial_column")],
    indirect=True,
)
def test_custom_trial_column_persists_through_the_orm(
    in_experiment_directory,
    db_session,
):
    experiment = get_experiment()
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    node = StaticNode(
        definition={"probe": True},
        module_id="custom_column_test",
        experiment=experiment,
    )
    experiment_package = experiment.__class__.__module__.rsplit(".", 1)[0]
    custom_trial_class = sys.modules[
        f"{experiment_package}.experiment"
    ].CustomColumnTrial
    trial = custom_trial_class(
        experiment=experiment,
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.item_id = "item-42"
    db.session.add_all([participant, node, trial])
    db.session.commit()
    db.session.expire_all()

    stored = custom_trial_class.query.one()
    assert stored.item_id == "item-42"
    assert stored.attempts == 0
