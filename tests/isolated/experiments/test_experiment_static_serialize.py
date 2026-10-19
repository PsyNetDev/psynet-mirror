import re

import pytest
from dallinger import db

import psynet.field  # noqa
from psynet.experiment import import_local_experiment
from psynet.pytest_psynet import path_to_test_experiment
from psynet.serialize import (
    PsyNetUnpickler,
    SerializedCallable,
    prepare_function_for_serialization,
    serialize,
    unserialize,
)
from psynet.trial.static import StaticNode, StaticTrial
from psynet.utils import call_function_with_context


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class Test:
    def test_psynet_method(self):
        import psynet.trial.main

        f = psynet.trial.main.Trial.call_async_post_trial
        f_serialized = serialize(f)
        assert (
            f_serialized
            == '{"py/function": "psynet.trial.main.Trial.call_async_post_trial"}'
        )
        assert unserialize(f_serialized) == f

    def test_psynet_method_2(self):
        from dallinger.models import Network

        network = Network()
        db.session.add(network)
        db.session.commit()

        net_serialized = serialize(network)
        assert re.match(
            '{"py/object": "dallinger.models.Network", "identifiers": {"id": [0-9]+}}',
            net_serialized,
        )
        network_2 = unserialize(net_serialized)
        assert network_2.id == network.id

    def test_config(self, trial, node, network, participant):
        # Checking that loading Dallinger config doesn't mess up the mappers in the way it used to
        self.check_mappers()

        import_local_experiment()

        from dallinger.config import get_config

        config = get_config()

        if not config.ready:
            config.load()

        self.check_mappers()

    def test_serialize_sql(self, trial, node, network, participant):
        trial_id = trial.id
        trial_serialized = serialize(trial)
        assert (
            trial_serialized
            == f'{{"py/object": "dallinger_experiment.experiment.AnimalTrial", "identifiers": {{"id": {trial_id}}}}}'
        )

        trial_unserialized = unserialize(trial_serialized)
        assert isinstance(trial_unserialized, StaticTrial)
        assert trial_unserialized.id == trial_id
        assert isinstance(trial.node, StaticNode)

        self.check_mappers()

    def test_serialize_custom_function(self):
        exp = import_local_experiment()

        f = exp["module"].test_imports.my_add
        f_serialized = serialize(f)

        assert (
            f_serialized
            == '{"py/function": "dallinger_experiment.test_imports.my_add"}'
        )

        f_unserialized = unserialize(f_serialized)
        assert f_unserialized(1, 4) == 5

        self.check_mappers()

    def test_serialize_custom_object(self):
        exp = import_local_experiment()

        obj = exp["module"].test_imports.MyClass(x=3)
        obj_serialized = serialize(obj)

        assert (
            obj_serialized
            == '{"py/object": "dallinger_experiment.test_imports.MyClass", "x": 3}'
        )

        obj_unserialized = unserialize(obj_serialized)
        assert isinstance(obj_unserialized, exp["module"].test_imports.MyClass)

        self.check_mappers()

    def test_serialize_custom_method(self):
        exp = import_local_experiment()

        method = exp["module"].test_imports.MyClass.add
        method_serialized = serialize(method)

        assert (
            method_serialized
            == '{"py/function": "dallinger_experiment.test_imports.MyClass.add"}'
        )

        method_unserialized = unserialize(method_serialized)
        assert method_unserialized == exp["module"].test_imports.MyClass.add

        self.check_mappers()

    def test_serialized_unknown_module(self):
        object_serialized = '{"py/object": "dallinger_experiment.abc.MyClass", "x": 3}'

        with pytest.raises(AttributeError):
            unserialize(object_serialized)

        # assert (
        #     str(e.value)
        #     == f"Tried to unserialize a custom object (dallinger_experiment.abc.MyClass) but couldn't find the requested module: 'abc'. You may need to make sure it's imported in experiment.py."
        # )

        self.check_mappers()

    def test_serialize_unknown_object(self):
        object_serialized = '{"py/object": "dallinger_experiment.test_imports.ABC"}'

        with pytest.raises(AttributeError):
            unserialize(object_serialized)

        # assert (
        #     str(e.value)
        #     == f"Tried to unserialize a custom object (dallinger_experiment.test_imports.ABC) but couldn't find the requested object: 'ABC'"
        # )

        self.check_mappers()

    def check_mappers(self):
        # If we don't manage the imports correctly, we can end up with a nasty bug where
        # SQLAlchemy Base.registry.mappers stops working, and instead throws an error
        # when you try to call it.
        from dallinger.db import Base

        assert Base.registry.mappers


def test_serialize_dominate_tag():
    from dominate import tags

    text = tags.p("Hello!")

    assert serialize(text) == '"<p>Hello!</p>"'


def test_serialize_lambda():
    with pytest.raises(TypeError, match="Cannot pickle lambda functions."):
        serialize(lambda x: x)


def test_unserialize():
    from psynet.trial.main import Trial

    unpickler = PsyNetUnpickler()

    obj = {"py/object": "psynet.trial.main.Trial", "identifiers": {"id": 9999999}}
    with pytest.warns(
        Warning,
        match="The unserializer failed to find the following object in the database",
    ):
        assert unpickler.load_sql_object(Trial, obj) is None


class MyClass2:
    x = 3

    @classmethod
    def add(cls, y):
        return cls.x + y


def return_experiment(experiment=None):
    return experiment


def test_serialize_class_method():
    obj = MyClass2()
    method = obj.add

    function, arguments = prepare_function_for_serialization(method, {"y": 3})

    method_serialized = serialize(function)
    assert (
        method_serialized
        == '{"py/function": "test_experiment_static_serialize.MyClass2.add"}'
    )
    method_unserialized = unserialize(method_serialized)

    assert method_unserialized(4) == 7


def test_serialized_callable_receives_context_arguments():
    serialized = SerializedCallable(function=return_experiment, arguments={})
    experiment = object()

    assert call_function_with_context(serialized, experiment=experiment) is experiment
