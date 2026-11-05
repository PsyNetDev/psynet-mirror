"""Live sessions: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

A game is a :class:`LiveSession` subclass, with a :class:`LiveMessage`
subclass for each kind of message its pages send. A
:class:`LiveSessionInitializer` in the timeline starts a session for each
group that reaches it, and a page with a :class:`LiveSessionControl` plays
it. :doc:`/code/multiplayer/live_sessions` walks through a whole game.
"""

from .control import LiveSessionControl
from .game import LiveSession
from .initializer import LiveSessionInitializer, live_session_id
from .messages import LiveMessage, SavedMessage
from .ready_step import NOT_STARTED, Ready
from .registry import live_session_game_types

__all__ = [
    "LiveMessage",
    "LiveSession",
    "LiveSessionControl",
    "LiveSessionInitializer",
    "NOT_STARTED",
    "Ready",
    "SavedMessage",
    "live_session_game_types",
    "live_session_id",
]
