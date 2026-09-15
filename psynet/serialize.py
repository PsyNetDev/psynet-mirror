import importlib
import inspect
import pickle
import types
import warnings
from dataclasses import dataclass
from functools import cached_property

import dominate.tags
import jsonpickle
import jsonpickle.ext.numpy as jsonpickle_numpy
from jsonpickle import Pickler
from jsonpickle.unpickler import Unpickler, loadclass
from jsonpickle.util import importable_name
from markupsafe import Markup

from .data import SQLBase, get_primary_key_values
from .utils import NoArgumentProvided, call_function_with_context, get_logger

logger = get_logger()


class CallableSerializationError(ValueError):
    """
    Raised when a callable cannot be serialized safely.
    """


@dataclass
class SerializedCallable:
    function: callable
    arguments: dict

    def __call__(
        self,
        *,
        participant=NoArgumentProvided,
        experiment=NoArgumentProvided,
        **kwargs,
    ):
        # TODO: Generalize this context forwarding to cover the other
        # callback/context args too, such as group, participants, barrier,
        # assets, nodes, trial_maker, and trial.
        # Should ideally do this without hardcoding the arguments.
        if participant is not NoArgumentProvided:
            kwargs["participant"] = participant
        if experiment is not NoArgumentProvided:
            kwargs["experiment"] = experiment
        merged = {**(self.arguments or {}), **kwargs}
        return call_function_with_context(self.function, **merged)


def serialize_callable(callable_obj, context: str):
    """
    Serialize a callable with centralized validation and error messaging.
    """
    if callable_obj is None or isinstance(callable_obj, SerializedCallable):
        return callable_obj
    if not callable(callable_obj):
        raise CallableSerializationError(
            _format_callable_error(
                context,
                f"Received {type(callable_obj).__name__}, which is not callable.",
            )
        )

    if inspect.ismethod(callable_obj) and callable_obj.__self__ is not None:
        method_self = callable_obj.__self__
        if isinstance(method_self, type):
            function, arguments = prepare_function_for_serialization(callable_obj, {})
            return SerializedCallable(function=function, arguments=arguments)
        if _is_trial_maker(method_self):
            return SerializedCallable(
                function=_call_trial_maker_method,
                arguments={
                    "trial_maker_id": method_self.id,
                    "method_name": callable_obj.__name__,
                },
            )
        if isinstance(method_self, SQLBase):
            _ensure_sql_primary_key(method_self, context)
            function, arguments = prepare_function_for_serialization(callable_obj, {})
            return SerializedCallable(function=function, arguments=arguments)

        raise CallableSerializationError(
            _format_callable_error(
                context,
                f"Provided a bound instance method ('{callable_obj.__qualname__}').",
            )
        )

    try:
        function, arguments = prepare_function_for_serialization(callable_obj, {})
    except Exception as err:
        raise CallableSerializationError(
            _format_callable_error(context, str(err))
        ) from err
    return SerializedCallable(function=function, arguments=arguments)


def _format_callable_error(context: str, detail: str) -> str:
    return (
        f"{context} must be a module-level function, a @staticmethod/@classmethod, "
        "or an instance method on a TrialMaker or ORM model with a primary key. "
        f"{detail}"
    )


def _is_trial_maker(instance) -> bool:
    from psynet.trial.main import TrialMaker

    return isinstance(instance, TrialMaker)


def _call_trial_maker_method(
    trial_maker_id: str,
    method_name: str,
    group=None,
    participants=None,
    participant=None,
    barrier=None,
    experiment=None,
):
    from psynet.experiment import get_trial_maker

    if not trial_maker_id:
        raise CallableSerializationError(
            _format_callable_error(
                "TrialMaker callable",
                "TrialMaker is missing an id. Ensure the TrialMaker is initialized.",
            )
        )
    trial_maker = get_trial_maker(trial_maker_id)
    method = getattr(trial_maker, method_name)
    return call_function_with_context(
        method,
        group=group,
        participants=participants,
        participant=participant,
        barrier=barrier,
        experiment=experiment,
    )


def _ensure_sql_primary_key(instance, context: str) -> None:
    primary_keys = get_primary_key_values(instance)
    if any(key is None for key in primary_keys.values()):
        raise CallableSerializationError(
            _format_callable_error(
                context,
                f"The ORM instance is missing a primary key: {primary_keys}.",
            )
        )


# Without jsonpickle.ext.numpy.register_handlers(), numpy arrays are serialized very verbosely, e.g.
# >>> serialize(np.array([1, 2, 3]))
# '{"py/reduce": [{"py/function": "numpy._core.multiarray._reconstruct"}, {"py/tuple": [{"py/type": "numpy.ndarray"},
# {"py/tuple": [0]}, {"py/b64": "Yg=="}]}, {"py/tuple": [1, {"py/tuple": [3]}, {"py/reduce": [{"py/type":
# "numpy.dtype"}, {"py/tuple": ["i8", false, true]}, {"py/tuple": [3, "<", null, null, null, -1, -1, 0]}]}, false,
# {"py/b64": "AQAAAAAAAAACAAAAAAAAAAMAAAAAAAAA"}]}]}'
#
# With jsonpickle.ext.numpy.register_handlers(), we get a much more concise representation:
# >>> serialize(np.array([1, 2, 3]))
# '{"py/object": "numpy.ndarray", "dtype": "int64", "values": [1, 2, 3]}'
jsonpickle_numpy.register_handlers()


def is_lambda_function(x):
    return callable(x) and hasattr(x, "__name__") and x.__name__ == "<lambda>"


class PsyNetPickler(Pickler):
    def flatten(self, obj, reset=True):
        if is_lambda_function(obj):
            try:
                source_file, source_line = (
                    obj.__code__.co_filename,
                    obj.__code__.co_firstlineno,
                )
            except Exception as e:
                source_file, source_line = "UNKNOWN", "UNKNOWN"
                logger.error(
                    msg="Failed to find source code for lambda function.", exc_info=e
                )
            raise TypeError(
                "Cannot pickle lambda functions. "
                "Can you replace this function with a named function defined by `def`?\n"
                f"The problematic function was defined in {source_file} "
                f"on line {source_line}."
            )
        else:
            return super().flatten(obj, reset=reset)


class PsyNetUnpickler(Unpickler):
    """
    The PsyNetUnpickler class
    """

    # def _restore(self, obj):
    #     print(obj)
    #     if isinstance(obj, dict) and "py/object" in obj:
    #         if obj["py/object"].startswith("dallinger_experiment"):
    #             cls = self.get_experiment_object(obj["py/object"])
    #             if hasattr(cls, "_sa_registry"):
    #                 return self.load_sql_object(cls, obj)
    #             else:
    #                 self.register_classes(cls)
    #                 return super()._restore(obj)
    #
    #     if isinstance(obj, dict) and "py/function" in obj:
    #         if obj["py/function"].startswith("dallinger_experiment"):
    #             return self.get_experiment_object(obj["py/function"])
    #
    #             # import pydevd_pycharm
    #             # pydevd_pycharm.settrace('localhost', port=12345, stdoutToServer=True, stderrToServer=True)
    #
    #     return super()._restore(obj)

    def _restore_object(self, obj):
        cls_id = obj["py/object"]
        if cls_id.startswith("dallinger_experiment"):
            cls = self.get_experiment_object(cls_id)
        else:
            cls = loadclass(cls_id)
        is_sql_object = hasattr(cls, "_sa_registry")
        if is_sql_object:
            return self.load_sql_object(cls, obj)
        else:
            self.register_classes(cls)
            return super()._restore_object(obj)

    def _restore_function(self, obj):
        if isinstance(obj, dict) and "py/function" in obj:
            if obj["py/function"].startswith("dallinger_experiment"):
                return self.get_experiment_object(obj["py/function"])
        return super()._restore_function(obj)

    def get_experiment_object(self, spec):
        split = spec.split(".")
        package_spec = split[0]
        remainder_spec = split[1:]

        assert package_spec == "dallinger_experiment"

        current = self.experiment["package"]
        for x in remainder_spec:
            current = getattr(current, x)

        return current

    def load_sql_object(self, cls, obj):
        identifiers = obj["identifiers"]
        res = cls.query.filter_by(**identifiers).one_or_none()
        if res is None:
            warnings.warn(
                f"The unserializer failed to find the following object in the database: {obj}. "
                "Returning `None` instead."
            )
        return res

    @cached_property
    def experiment(self):
        from .experiment import import_local_experiment

        return import_local_experiment()


def serialize(x, **kwargs):
    pickler = PsyNetPickler()
    keys = kwargs.pop("keys", True)
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="jsonpickle cannot pickle")
        return jsonpickle.encode(x, keys=keys, **kwargs, context=pickler, warn=True)


def to_dict(x):
    pickler = PsyNetPickler()
    return pickler.flatten(x)


def unserialize(x):
    # If we don't provide the custom classes directly, jsonpickle tries to find them itself,
    # and ends up messing up the SQLAlchemy mapper registration system,
    # producing duplicate mappers for each custom class.
    # import_local_experiment()
    # custom_classes = list(get_custom_sql_classes().values())
    # return jsonpickle.decode(x, context=unpickler, classes=custom_classes)
    unpickler = PsyNetUnpickler()
    return jsonpickle.decode(x, context=unpickler)
    # return jsonpickle.decode(x, classes=custom_classes)


# These classes cannot be reliably pickled by the `jsonpickle` library.
# Instead we fall back to Python's built-in pickle library.
no_json_classes = [Markup]


class NoJSONHandler(jsonpickle.handlers.BaseHandler):
    """
    The NoJSONHandler class
    """

    def flatten(self, obj, state):
        state["bytes"] = pickle.dumps(obj, 0).decode("latin-1")
        return state

    def restore(self, state):
        return pickle.loads(state["bytes"].encode("latin-1"))


for _cls in no_json_classes:
    jsonpickle.register(_cls, NoJSONHandler, base=True)


class SQLHandler(jsonpickle.handlers.BaseHandler):
    """
    The SQLHandler class
    """

    def get_primary_keys(self, obj):
        return get_primary_key_values(obj)

    def flatten(self, obj, state):
        primary_keys = self.get_primary_keys(obj)
        if any(key is None for key in primary_keys.values()):
            raise ValueError(
                f"Cannot serialize {obj}. It has a `None` value for one of its primary keys: {primary_keys}. "
                "It might be possible to solve this problem by introducing a `db.session.flush()` call before pickling."
            )
        state["identifiers"] = primary_keys
        return state

    def restore(self, state):
        raise RuntimeError("This should not be called directly")


jsonpickle.register(SQLBase, SQLHandler, base=True)


class DominateHandler(jsonpickle.handlers.BaseHandler):
    """
    The DominateHandler class
    """

    def flatten(self, obj, state):
        return str(obj)


jsonpickle.register(dominate.dom_tag.dom_tag, DominateHandler, base=True)


def _callable_to_path(function):
    if inspect.ismethod(function):
        if function.__self__ is not None and not inspect.isclass(function.__self__):
            raise TypeError("Cannot serialize bound instance methods.")
        function = function.__func__

    if getattr(function, "__name__", None) == "<lambda>":
        raise TypeError("Cannot serialize lambda functions.")

    if "<locals>" in getattr(function, "__qualname__", ""):
        raise TypeError("Cannot serialize functions defined within other functions.")

    module = getattr(function, "__module__", None)
    if not module:
        raise TypeError("Cannot serialize callables without a module.")

    return f"{module}.{function.__qualname__}"


def _callable_from_path(path):
    module_name, qualname = path.split(".", 1)
    module = importlib.import_module(module_name)
    target = module
    for attr in qualname.split("."):
        target = getattr(target, attr)
    return target


class CallableHandler(jsonpickle.handlers.BaseHandler):
    def flatten(self, obj, state):
        return {"py/function": _callable_to_path(obj)}

    def restore(self, state):
        return _callable_from_path(state["py/function"])


jsonpickle.register(types.FunctionType, CallableHandler, base=True)
jsonpickle.register(types.MethodType, CallableHandler, base=True)


def prepare_function_for_serialization(function, arguments):
    if inspect.ismethod(function):
        method_name = function.__name__
        method_caller = function.__self__
        if isinstance(method_caller, type):
            function, arguments = prepare_class_method_for_serialization(
                function, arguments
            )
        else:
            function, arguments = prepare_instance_method_for_serialization(
                method_caller, method_name, arguments
            )

    check_that_function_can_be_serialized(function)

    return function, arguments


def prepare_class_method_for_serialization(function, arguments):
    """
    Prepares a class method for serialization by jsonpickle.
    This is necessary because jsonpickle can't serialize class methods directly.
    Instead, we serialize the underlying function.
    """
    # Since we are converting the class method into an ordinary function, I had thought we would need to add `cls`
    # to the arguments, but it turns out that when jsonpickle unserializes the function, it automatically turns
    # it back into a classmethod, so we don't need to do this after all.
    function = function.__func__
    return function, arguments


def prepare_instance_method_for_serialization(method_caller, method_name, arguments):
    """
    Prepares an instance method for serialization by jsonpickle.
    This is necessary because jsonpickle can't serialize instance methods directly.
    Instead, we turn it into an ordinary function where ``self`` is an argument.
    """
    function = getattr(method_caller.__class__, method_name)
    arguments["self"] = method_caller
    return function, arguments


def check_that_function_can_be_serialized(function):
    assert callable(function)
    if "<locals>" in importable_name(function):
        raise ValueError(
            "You cannot serialize a lambda function or a function defined within another function."
        )
