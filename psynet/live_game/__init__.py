"""Live games: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

A game is a :class:`LiveGame` subclass, with a :class:`LiveMessage`
subclass for each kind of message its pages send. A
:class:`PlayLiveGame` in the timeline starts a game for each
group that reaches it, and its page, which has a :class:`LiveGameControl`,
plays it. :doc:`/code/multiplayer/live_games` walks through a whole game.
"""

from .control import LiveGameControl
from .game import LiveGame
from .messages import LiveMessage, SavedMessage
from .play import PlayLiveGame, live_game_id
from .psynet_entry import NOT_STARTED, TIMEOUT, PlayerReady
from .registry import live_game_classes
from .result import LiveGameResult, live_game_result

__all__ = [
    "LiveMessage",
    "LiveGame",
    "LiveGameControl",
    "PlayLiveGame",
    "LiveGameResult",
    "NOT_STARTED",
    "PlayerReady",
    "SavedMessage",
    "TIMEOUT",
    "live_game_classes",
    "live_game_id",
    "live_game_result",
]
