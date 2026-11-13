"""Live sessions: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

A game is a :class:`LiveGame` subclass, with a :class:`LiveMessage`
subclass for each kind of message its pages send. A
:class:`PlayLiveGame` in the timeline starts a session for each
group that reaches it, and its page, which has a :class:`LiveSessionControl`,
plays it. :doc:`/code/multiplayer/live_sessions` walks through a whole game.
"""

from .control import LiveSessionControl
from .game import LiveGame
from .messages import LiveMessage, SavedMessage
from .play import PlayLiveGame, live_session_id
from .ready_step import NOT_STARTED, PlayerReady
from .registry import live_game_classes
from .result import LiveSessionResult, live_session_result

__all__ = [
    "LiveMessage",
    "LiveGame",
    "LiveSessionControl",
    "PlayLiveGame",
    "LiveSessionResult",
    "NOT_STARTED",
    "PlayerReady",
    "SavedMessage",
    "live_game_classes",
    "live_session_id",
    "live_session_result",
]
