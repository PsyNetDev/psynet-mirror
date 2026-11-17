"""Live games: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

A game is a :class:`LiveGame` subclass, with a :class:`LiveMessage`
subclass for each kind of message its pages send. A
:class:`PlayLiveGame` in the timeline starts a game for each
group that reaches it, and its page, which has a :class:`LiveGameControl`,
plays it. :doc:`/code/multiplayer/live_game_tutorial` walks through whole
games, and :doc:`/code/multiplayer/live_games` is the reference.
"""

from dallinger.realtime import Reject

from .control import LiveGameControl
from .game import LiveGame
from .history import LiveGameCheckpoint, LiveGameMoment
from .messages import LiveMessage, SavedMessage
from .play import PlayLiveGame
from .psynet_entry import NOT_STARTED, PLAYERS_LEFT, TIMEOUT, PlayerReady
from .record import LiveGameRecord
from .registry import live_game_classes

__all__ = [
    "LiveMessage",
    "LiveGame",
    "LiveGameCheckpoint",
    "LiveGameControl",
    "LiveGameMoment",
    "PlayLiveGame",
    "LiveGameRecord",
    "NOT_STARTED",
    "PlayerReady",
    "PLAYERS_LEFT",
    "Reject",
    "SavedMessage",
    "TIMEOUT",
    "live_game_classes",
]
