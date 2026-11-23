"""The live games defined so far, by name."""

# Every LiveGame subclass that sets a name, by name (Dallinger's channel). It is one
# registry for the whole process, because a PlayLiveGame built in a trial's
# show_trial isn't known when the experiment class is created.
_live_game_classes = {}


def live_game_classes():
    """Return every :class:`LiveGame` subclass that has a ``name``,
    which PsyNet adds to the experiment's ``realtime_games``."""
    return list(_live_game_classes.values())


def _live_game_class(channel):
    return _live_game_classes.get(channel)


def _register_live_game(game_class):
    channel = game_class.channel
    existing = _live_game_classes.get(channel)
    if existing is not None and not _same_definition(existing, game_class):
        if existing.__qualname__ == game_class.__qualname__:
            raise ValueError(
                f"{game_class.__qualname__} is defined in both {existing.__module__} "
                f"and {game_class.__module__}, with the name {channel!r}. If "
                "that is one file imported under two names, import it one way."
            )
        raise ValueError(
            f"{existing.__name__} and {game_class.__name__} both use the name "
            f"{channel!r}. A subclass of a game needs a name of its own."
        )
    _live_game_classes[channel] = game_class


def _same_definition(first, second):
    # Dallinger's tests run experiment.py again, and its verification imports
    # a copy of it under the same module name, defining its classes again.
    return (first.__module__, first.__qualname__) == (
        second.__module__,
        second.__qualname__,
    )
