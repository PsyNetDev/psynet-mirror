"""Live games: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

A game is a :class:`LiveGame` subclass, with a :class:`LiveMessage`
subclass for each kind of message its pages send. A
:class:`PlayLiveGame` in the timeline starts a game for each
group that reaches it, and its page, a :class:`LiveGamePage`, plays it. :doc:`/code/multiplayer/live_game_tutorial` walks through whole
games, and :doc:`the reference </code/multiplayer/live_games>` covers the
rest.
"""

from dallinger.realtime import Reject

from .control import LiveGamePage
from .game import LiveGame
from .messages import LiveMessage, SavedMessage
from .play import PlayLiveGame
from .psynet_entry import NOT_STARTED, PLAYERS_LEFT, TIMEOUT, TOO_LATE, PlayerReady
from .record import (
    LiveGameCheckpoint,
    LiveGameFailed,
    LiveGameMoment,
    LiveGameRecord,
)
from .registry import live_game_classes
from .trials import LiveTrialGame, TrialAnswer

__all__ = [
    "LiveTrialGame",
    "TrialAnswer",
    "LiveMessage",
    "LiveGame",
    "LiveGameCheckpoint",
    "LiveGameMoment",
    "LiveGamePage",
    "PlayLiveGame",
    "LiveGameFailed",
    "LiveGameRecord",
    "NOT_STARTED",
    "PlayerReady",
    "PLAYERS_LEFT",
    "Reject",
    "SavedMessage",
    "TIMEOUT",
    "TOO_LATE",
    "live_game_classes",
]
