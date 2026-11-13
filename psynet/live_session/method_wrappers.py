"""The wrappers LiveGame puts around a game's methods: the state's
conversion to JSON, the ready step and the game's duration."""

import contextvars
import functools

from dallinger.realtime import Reject
from pydantic_core import to_jsonable_python

from .messages import LiveMessage
from .ready_step import _READY_STEP, _UNCHANGED, PlayerReady, _ready_step

# The game methods that can change the state, which is converted after each.
_STATE_METHODS = ("apply", "tick", "on_join", "on_leave", "on_start")


# Set while a state method runs, so one that calls another, as through
# super() or from initial_state, converts once, after the outermost call.
# Converting rebuilds every dict and list in the state, which would cut off
# references the outer call still holds.
_changing_state = contextvars.ContextVar("_changing_state", default=False)


def _converts_outermost_call(method, name, convert):
    """Wrap the state method ``name`` so that ``convert(self, result, args)``
    runs after the outermost call only, and each call to the game's ``name``,
    as opposed to a ``super()`` call, goes through its entry in
    ``_READY_STEP``, if it has one."""
    ready_step = _READY_STEP.get(name)

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if ready_step is not None and getattr(type(self), name) is wrapper:
            call = functools.partial(ready_step, self, method)
        else:
            call = functools.partial(method, self)
        if _changing_state.get():
            result = call(*args, **kwargs)
            return None if result is _UNCHANGED else result

        # In a copy of the context, so nothing has to unset the flag, even
        # when Dallinger's time limit interrupts the call.
        def run():
            _changing_state.set(True)
            return call(*args, **kwargs)

        result = contextvars.copy_context().run(run)
        if result is _UNCHANGED:
            return None
        if not self.convert_state_to_json:
            return result
        return convert(self, result, args)

    wrapper._psynet_wrapper = True
    return wrapper


def _stores_json(method, name=None):
    name = name or method.__name__

    def convert_in_place(self, result, args):
        state = args[0]
        converted = _to_json(state, f"{type(self).__name__}.{name}")
        # Changed in place, since Dallinger keeps the state object.
        state.clear()
        state.update(converted)

    return _converts_outermost_call(method, name, convert_in_place)


def _returns_json(method, name):
    def convert_returned(self, state, args):
        return _to_json(state, f"{type(self).__name__}.{name}")

    return _converts_outermost_call(method, name, convert_returned)


def _waits_for_start(method):
    @functools.wraps(method)
    def next_deadline(self, state):
        ready_step = _ready_step(state)
        if ready_step["started_at"] is None:
            return self.ready_timeout
        deadline = method(self, state)
        ends_at = ready_step["ends_at"]
        if ends_at is None or ready_step["time_up"]:
            return deadline
        return ends_at if deadline is None else min(deadline, ends_at)

    next_deadline._psynet_wrapper = True
    return next_deadline


def _ends_when_time_is_up(method):
    @functools.wraps(method)
    def is_over(self, state):
        return _ready_step(state)["time_up"] or method(self, state)

    is_over._psynet_wrapper = True
    return is_over


def _shows_ready_step(method):
    @functools.wraps(method)
    def view(self, state, player_id):
        shown = method(self, state, player_id)
        if type(self).view is not view:
            return shown
        if not isinstance(shown, dict):
            raise TypeError(
                f"{type(self).__name__}.view must return a dict, not "
                f"{type(shown).__name__}."
            )
        ready_step = _ready_step(state)
        # A view can be the state itself.
        if shown.get("live_session", ready_step) != ready_step:
            raise ValueError(
                f"{type(self).__name__}.view returned a 'live_session' entry, "
                "which is PsyNet's. Give it another name."
            )
        return {**shown, "live_session": ready_step}

    view._psynet_wrapper = True
    return view


def _sends_message(method):
    @functools.wraps(method)
    def send(self, view, player_id, now):
        outermost = type(self).bot is send
        if outermost:
            ready_step = _ready_step(view, "view")
            if player_id not in ready_step["ready"]:
                return {"type": PlayerReady.type, "message": {}}
            if ready_step["started_at"] is None:
                return None
        message = method(self, view, player_id, now)
        # A bot calling super().bot() reaches its parent's wrapper, which
        # leaves the message for the outermost one.
        if not outermost or not isinstance(message, LiveMessage):
            return message
        sent = {
            "type": message.type,
            "message": message.model_dump(mode="json", by_alias=True),
        }
        # No page sees a bot's rejections, so a message the game can't read
        # fails the session here.
        try:
            read = self.read_message(sent)
        except Reject as rejection:
            problem = rejection.reason
        else:
            if read == message:
                return sent
            problem = f"It reads back as {read!r}."
        raise TypeError(
            f"{type(self).__name__}.bot returned {message!r}, which the game "
            f"can't read as it is. {problem} A bot can also return what a page "
            "sends, as a dict."
        )

    send._psynet_wrapper = True
    return send


def _to_json(state, what):
    key = _non_string_key(state)
    if key is not None:
        raise ValueError(
            f"After {what}, the state has a dict with the key {key!r}, of type "
            f"{type(key).__name__}. The state is saved as JSON, whose keys are "
            f"strings, so after a save the key would read back as {str(key)!r} "
            "and looking it up would fail. Use string keys: player ids are "
            "already strings."
        )
    try:
        return to_jsonable_python(state)
    except (ValueError, TypeError) as error:
        raise ValueError(
            f"After {what}, the state holds a value PsyNet can't convert to "
            f"JSON. {error}."
        ) from None


def _non_string_key(value, seen=None):
    """Return the first dict key in ``value`` that isn't a string, or None."""
    if isinstance(value, (dict, list, tuple)):
        seen = set() if seen is None else seen
        # A value that contains itself is left for the conversion to report.
        if id(value) in seen:
            return None
        seen.add(id(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return key
            found = _non_string_key(item, seen)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _non_string_key(item, seen)
            if found is not None:
                return found
    return None
