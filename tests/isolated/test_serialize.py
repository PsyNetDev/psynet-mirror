import datetime
import math
from functools import partial

import jsonpickle
import numpy as np
import pytest
from markupsafe import Markup

import psynet.experiment
from psynet.serialize import (
    CallableSerializationError,
    PsyNetUnpickler,
    serialize,
    serialize_callable,
    unserialize,
)
from psynet.trial.main import TrialMaker

shared = {"x": 1}


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        2**70,
        1.5,
        float("inf"),
        "é ünïcode",
        'user text mentioning "py/object" and json://',
        {"a": [1, {"b": None}], "c": "d"},
        [shared, shared],
        {"k": (1, 2)},
        {1, 2},
        np.array([1, 2]),
        Markup("<b>x</b>"),
        datetime.datetime(2026, 1, 1),
        len,
    ],
)
def test_unserialize_matches_jsonpickle(value):
    encoded = serialize(value)
    expected = jsonpickle.decode(encoded, context=PsyNetUnpickler())

    decoded = unserialize(encoded)

    assert type(decoded) is type(expected)
    if isinstance(expected, np.ndarray):
        assert (decoded == expected).all()
    else:
        assert decoded == expected


def _outcome(decode, text):
    try:
        return "value", decode(text)
    except Exception as err:
        return "error", type(err)


@pytest.mark.parametrize("text", ["", "hello", "{'a': 1}"])
def test_unserialize_handles_non_json_text_like_jsonpickle(text):
    # jsonpickle falls back to YAML only when PyYAML is installed.
    expected = _outcome(lambda t: jsonpickle.decode(t, context=PsyNetUnpickler()), text)
    assert _outcome(unserialize, text) == expected


def test_unserialize_decodes_plain_json_without_jsonpickle(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("jsonpickle used for plain JSON")

    monkeypatch.setattr(jsonpickle, "decode", fail)

    assert unserialize('{"a": [1, 2.5, null, true, "py"]}') == {
        "a": [1, 2.5, None, True, "py"]
    }
    assert math.isnan(unserialize("NaN"))


def _score(group, question):
    return group, question


class _ScoringTrialMaker(TrialMaker):
    def score(self, group, question):
        return group, question


@pytest.mark.parametrize(
    "callback",
    [
        partial(_score, 1),
        partial(_score, group="g"),
        partial(_score, typo=1),
        partial(lambda group, question: None, question=1),
    ],
)
def test_partial_callbacks_reject_arguments_that_would_be_lost(callback):
    with pytest.raises(CallableSerializationError):
        serialize_callable(callback, "on_release")


def test_partial_of_a_trial_maker_method_keeps_its_arguments(monkeypatch):
    trial_maker = _ScoringTrialMaker.__new__(_ScoringTrialMaker)
    trial_maker.id = "scoring"
    monkeypatch.setattr(psynet.experiment, "get_trial_maker", lambda id_: trial_maker)
    monkeypatch.setattr(psynet.experiment, "get_experiment", lambda: None)
    callback = serialize_callable(partial(trial_maker.score, question=1), "on_release")
    assert callback(group="g") == ("g", 1)
