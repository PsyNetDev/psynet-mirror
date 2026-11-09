import datetime
import math

import jsonpickle
import numpy as np
import pytest
from markupsafe import Markup

from psynet.serialize import PsyNetUnpickler, serialize, unserialize

shared = {"x": 1}

_VALUES = [
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
    {12: "rock", "b": {0: shared}, "c": shared},
    {"s": {"json://k": shared}, "t": shared, 2: [{3: None}]},
    {1, 2},
    np.array([1, 2]),
    Markup("<b>x</b>"),
    datetime.datetime(2026, 1, 1),
    len,
]


@pytest.mark.parametrize("value", _VALUES)
def test_serialize_matches_jsonpickle(value):
    """PsyNetPickler's single-pass shortcut for string-keyed dictionaries must not change the output."""
    assert serialize(value) == jsonpickle.encode(value, keys=True)


@pytest.mark.parametrize("value", _VALUES)
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


@pytest.mark.parametrize(
    "value",
    [
        {12: "rock", 15: "paper"},
        {"round": {0: [1, 2]}},
        {(1, 2): "x", None: "y", 1.5: "z", True: "w"},
        {"12": "a string key stays a string"},
    ],
)
def test_dictionary_keys_keep_their_type(value):
    """Integer participant IDs used as keys, for example, come back as integers."""
    decoded = unserialize(serialize(value))
    assert decoded == value
    assert [type(k) for k in decoded] == [type(k) for k in value]


def test_mixed_key_dictionaries_keep_key_types_but_not_order():
    decoded = unserialize(serialize({1: "a", "b": 2, 3: "c"}))
    assert list(decoded.items()) == [("b", 2), (1, "a"), (3, "c")]


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
