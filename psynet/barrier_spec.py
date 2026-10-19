"""Declarative persistence for barrier release behavior.

Barrier instances must survive across web workers, but persisting an entire
``Barrier`` object also captures waiting pages and incidental ORM state.
This module stores the importable barrier class, release-hook state, scalar
presentation (``content``, timeouts), and arrival-notice settings. Waiting
pages and hold-page construction (``waiting_logic``, ``_uses_timeline_hold``,
``waiting_logic_expected_repetitions``) stay on the live timeline object.
See :class:`~psynet.sync.Barrier` for which methods are live-only.
Callback identity is kept separate from the ORM receiver selected for one
visit, so behavior comparisons are stable while invocation remains correctly
bound.
"""

import hashlib
import json

from jsonpickle.unpickler import loadclass
from jsonpickle.util import importable_name
from markupsafe import Markup

from psynet.data import SQLBase, get_primary_key_values
from psynet.serialize import (
    SerializedCallable,
    callable_from_path,
    callable_to_path,
    serialize_callable,
)

SPEC_VERSION = 1

_PAGE_FIELDS = {
    "_uses_timeline_hold",
    "waiting_logic",
    "waiting_logic_expected_repetitions",
}

_PRESENTATION_FIELDS = {
    "content",
    "expected_wait",
    "fix_time_credit",
    "max_wait_action",
    "max_wait_time",
}

_NOTIFICATION_FIELDS = {"notify_arrivals", "on_arrival_message"}

_EXCLUDED_FROM_STATE = _PAGE_FIELDS | _PRESENTATION_FIELDS | _NOTIFICATION_FIELDS


class BarrierSpecError(ValueError):
    """Raised when barrier behavior cannot be represented declaratively."""


def _importable_class_path(cls, context):
    """Return an import path that round-trips through ``loadclass``."""
    path = importable_name(cls)
    qualname = getattr(cls, "__qualname__", "")
    if "<locals>" in path or "<locals>" in qualname:
        raise BarrierSpecError(
            f"{context} is a local class and cannot be reconstructed. "
            "Define the class at module level."
        )
    loaded = loadclass(path)
    if loaded is None:
        raise BarrierSpecError(
            f"{context} class {path!r} cannot be imported after encoding."
        )
    return path


def barrier_spec(barrier):
    """Return a JSON-compatible specification of a barrier's release behavior."""
    class_name = barrier.__class__.__name__
    state = {
        key: _encode_value(value, context=f"{class_name}.{key}")
        for key, value in vars(barrier).items()
        if key not in _EXCLUDED_FROM_STATE
    }
    spec = {
        "version": SPEC_VERSION,
        "class": _importable_class_path(barrier.__class__, class_name),
        "state": state,
    }
    presentation = _encode_field_group(barrier, _PRESENTATION_FIELDS)
    if presentation:
        spec["presentation"] = presentation
    notifications = _encode_field_group(barrier, _NOTIFICATION_FIELDS)
    if notifications:
        spec["notifications"] = notifications
    return spec


def _encode_field_group(barrier, field_names):
    """Encode named attributes that exist on ``barrier``."""
    encoded = {}
    for key in field_names:
        if key not in vars(barrier):
            continue
        encoded[key] = _encode_value(
            getattr(barrier, key),
            context=f"{barrier.__class__.__name__}.{key}",
        )
    return encoded


def barrier_spec_json(barrier):
    """Serialize release behavior to canonical JSON."""
    return _canonical_json(barrier_spec(barrier))


def barrier_from_spec_json(serialized):
    """Reconstruct a registry barrier from canonical JSON.

    The result is a callback/release object: scalar presentation and
    notifications are restored. Waiting pages and hold-page construction stay
    on the live timeline barrier. See :class:`~psynet.sync.Barrier` for which
    methods are live-only.
    """
    try:
        spec = json.loads(serialized)
    except (TypeError, json.JSONDecodeError) as err:
        raise BarrierSpecError("Barrier spec must be valid JSON.") from err
    if not isinstance(spec, dict):
        raise BarrierSpecError("Barrier spec must be a JSON object.")
    if spec.get("version") != SPEC_VERSION:
        raise BarrierSpecError(
            f"Unsupported barrier spec version {spec.get('version')!r}."
        )
    try:
        barrier_class = loadclass(spec["class"])
    except (KeyError, ImportError, AttributeError) as err:
        raise BarrierSpecError(
            "Barrier spec class is missing or cannot be imported."
        ) from err
    if barrier_class is None:
        raise BarrierSpecError(
            f"Barrier spec class {spec.get('class')!r} cannot be imported."
        )
    state = spec.get("state")
    if not isinstance(state, dict):
        raise BarrierSpecError("Barrier spec state must be an object.")
    barrier = barrier_class.__new__(barrier_class)
    for key, value in state.items():
        setattr(barrier, key, _decode_value(value))
    for key, value in spec.get("presentation", {}).items():
        setattr(barrier, key, _decode_value(value))
    for key, value in spec.get("notifications", {}).items():
        setattr(barrier, key, _decode_value(value))
    return barrier


def behavior_hash(barrier):
    """Return a stable hash of release behavior, excluding callback receivers."""
    return behavior_hash_from_json(barrier_spec_json(barrier))


def behavior_hash_from_json(serialized):
    """Hash a serialized spec after removing visit-local callback bindings."""
    spec = json.loads(serialized)
    identity = _behavior_identity(spec)
    return hashlib.sha256(_canonical_json(identity).encode()).hexdigest()


def _encode_value(value, *, context):
    if isinstance(value, Markup):
        return {"__type__": "markup", "html": str(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, SerializedCallable):
        return _encode_callable(value, context=context)
    if isinstance(value, SQLBase):
        identifiers = get_primary_key_values(value)
        if any(identifier is None for identifier in identifiers.values()):
            raise BarrierSpecError(
                f"{context} references an ORM object without a complete primary key."
            )
        return {
            "__type__": "orm",
            "class": importable_name(value.__class__),
            "identifiers": _encode_value(identifiers, context=f"{context}.identifiers"),
        }
    if isinstance(value, type):
        return {
            "__type__": "class",
            "path": _importable_class_path(value, context),
        }
    if callable(value):
        return _encode_callable(serialize_callable(value, context), context=context)
    if isinstance(value, list):
        return [_encode_value(item, context=f"{context}[]") for item in value]
    if isinstance(value, tuple):
        return {
            "__type__": "tuple",
            "items": [_encode_value(item, context=f"{context}[]") for item in value],
        }
    if isinstance(value, set):
        items = [_encode_value(item, context=f"{context}[]") for item in value]
        return {"__type__": "set", "items": sorted(items, key=_canonical_json)}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise BarrierSpecError(f"{context} contains a non-string dictionary key.")
        if "__type__" in value:
            raise BarrierSpecError(f"{context} uses the reserved '__type__' key.")
        return {
            key: _encode_value(item, context=f"{context}.{key}")
            for key, item in value.items()
        }
    raise BarrierSpecError(
        f"{context} contains unsupported state of type {type(value).__name__}."
    )


def _encode_callable(value, *, context):
    try:
        path = callable_to_path(value.function)
    except (TypeError, ValueError) as err:
        raise BarrierSpecError(f"{context} has an unsupported callback.") from err
    return {
        "__type__": "callable",
        "function": path,
        "arguments": _encode_value(
            value.arguments or {}, context=f"{context}.arguments"
        ),
    }


def _decode_value(value):
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    if not isinstance(value, dict) or "__type__" not in value:
        if isinstance(value, dict):
            return {key: _decode_value(item) for key, item in value.items()}
        return value
    kind = value["__type__"]
    if kind == "callable":
        return SerializedCallable(
            function=callable_from_path(value["function"]),
            arguments=_decode_value(value["arguments"]),
        )
    if kind == "orm":
        model = loadclass(value["class"])
        if model is None:
            raise BarrierSpecError(f"ORM class {value['class']!r} cannot be imported.")
        identifiers = _decode_value(value["identifiers"])
        instance = model.query.filter_by(**identifiers).one_or_none()
        if instance is None:
            raise BarrierSpecError(
                f"ORM callback receiver {value['class']} "
                f"{identifiers} no longer exists."
            )
        return instance
    if kind == "markup":
        return Markup(value["html"])
    if kind == "class":
        cls = loadclass(value["path"])
        if cls is None:
            raise BarrierSpecError(f"Class {value['path']!r} cannot be imported.")
        return cls
    if kind == "tuple":
        return tuple(_decode_value(item) for item in value["items"])
    if kind == "set":
        return {_decode_value(item) for item in value["items"]}
    raise BarrierSpecError(f"Unknown barrier spec value type {kind!r}.")


def _behavior_identity(spec):
    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("__type__") == "callable":
            callback = {key: normalize(item) for key, item in value.items()}
            receiver = callback["arguments"].get("self")
            if isinstance(receiver, dict) and receiver.get("__type__") == "orm":
                callback["arguments"]["self"] = {
                    "__type__": "orm_class",
                    "class": receiver["class"],
                }
            return callback
        return {key: normalize(item) for key, item in value.items()}

    identity = normalize(spec)
    identity.pop("presentation", None)
    identity.pop("notifications", None)
    return identity


def _canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except ValueError as err:
        raise BarrierSpecError(
            "Barrier spec contains a non-JSON numeric value."
        ) from err
