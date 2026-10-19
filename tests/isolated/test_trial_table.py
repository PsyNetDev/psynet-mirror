"""Trial is an independent PsyNet table, not a Dallinger Info subclass."""

from dallinger.models import Info

from psynet.data import sql_base_classes
from psynet.trial.main import Trial, TrialNode


def test_trial_uses_independent_table():
    assert Trial.__tablename__ == "trial"
    assert not issubclass(Trial, Info)
    assert sql_base_classes()["trial"] is Trial


def test_trial_parent_fk_targets_trial_table():
    fk = next(iter(Trial.parent_trial_id.property.columns[0].foreign_keys))
    assert fk.column.table.name == "trial"
    assert fk.column.name == "id"


def test_trial_base_class_name_for_repr():
    # SQLMixinDallinger.__repr__ uses get_sql_base_class(self).__name__.
    assert sql_base_classes()["trial"].__name__ == "Trial"


def test_trial_node_failure_cascade_targets_alive_trials():
    alive = [object(), object()]
    stub = type("StubNode", (), {"alive_trials": alive})()
    cascade = TrialNode.failure_cascade.fget(stub)
    assert len(cascade) == 1
    assert cascade[0]() == alive
