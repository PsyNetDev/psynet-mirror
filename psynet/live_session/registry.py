"""The live session games defined so far, by channel."""

# Every LiveSession subclass that sets a channel, by channel.
_live_session_types = {}


def live_session_game_types():
    """Return every :class:`LiveSession` subclass that has a ``channel``,
    which PsyNet adds to the experiment's ``realtime_games``."""
    return list(_live_session_types.values())


def _live_session_type(channel):
    return _live_session_types.get(channel)


def _register_live_session(game_type):
    channel = game_type.channel
    existing = _live_session_types.get(channel)
    if existing is not None and not _same_definition(existing, game_type):
        if existing.__qualname__ == game_type.__qualname__:
            raise ValueError(
                f"{game_type.__qualname__} is defined in both {existing.__module__} "
                f"and {game_type.__module__}, with the channel {channel!r}. If "
                "that is one file imported under two names, import it one way."
            )
        raise ValueError(
            f"{existing.__name__} and {game_type.__name__} both use the channel "
            f"{channel!r}. A subclass of a game needs a channel of its own."
        )
    _live_session_types[channel] = game_type


def _same_definition(first, second):
    # Dallinger's tests run experiment.py again, and its verification imports
    # a copy of it under the same module name, defining its classes again.
    return (first.__module__, first.__qualname__) == (
        second.__module__,
        second.__qualname__,
    )
