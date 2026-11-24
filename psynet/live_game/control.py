"""LiveGameControl, the control that joins a game page to its game, and
LiveGamePage, a ModularPage with that control.

The control has the page load ``live-game.js``. Its page code creates
``psynet.liveGame`` and leaves the game when the participant leaves
the page. ``get_participant_page_config`` gives the script the game's id and
channel each time the page renders. ``check_ready_for_response`` refuses the
page's response until the game's result is saved, and ``validate`` then
sets the answer to what the game's ``answer`` returns for the participant.
The game pays its rewards itself, when the game's result is saved.
"""

from datetime import timedelta

from dallinger.models import timenow
from dominate import tags
from dominate.util import raw

from ..modular_page import ModularPage, NullControl, Prompt
from ..page import _authored_html
from ..sync import _removed_from_group_notice
from ..timeline import ResponseNotReady
from ..utils import get_translator
from .play import _check_reached_game, _live_game_id, _set_live_game_answer
from .psynet_entry import TOO_LATE
from .record import (
    LiveGameFailed,
    LiveGameRecord,
    LiveGameStatus,
    _computed_answer,
    _done_reason,
    _session_channel,
    _session_columns,
    _session_game_class,
    _session_participant_ids,
    _too_late_players,
)

# Seconds a page waits before resending a response refused because the
# game's result isn't saved yet.
_RETRY_AFTER = 1

# Seconds past its max_duration that a game may take to save its result.
# One still running after that will never end.
_SAVING_MARGIN = 60

# The default text of a notice, translated as the page renders.
_DEFAULT = object()

# How a game page shows the other players.
_NAMES = ("shown", "anonymous")


class LiveGameControl(NullControl):
    """The control of a :class:`LiveGamePage`, which plays the group's live
    game. The page makes it from its own options, which it describes."""

    def __init__(
        self,
        auto_advance=True,
        show_result_for=0,
        player_left_message=_DEFAULT,
        no_game_message=_DEFAULT,
        too_late_message=_DEFAULT,
        waiting_status=_DEFAULT,
        ended_status=_DEFAULT,
        names="shown",
        player_info=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if names not in _NAMES:
            raise ValueError(
                f"A live game page's names must be one of "
                f"{', '.join(map(repr, _NAMES))}, not {names!r}."
            )
        if player_info is not None and not callable(player_info):
            raise TypeError(
                "A live game page's player_info must be a function of the "
                f"participant, not {player_info!r}."
            )
        if (
            isinstance(show_result_for, bool)
            or not isinstance(show_result_for, (int, float))
            or show_result_for < 0
        ):
            raise ValueError(
                f"show_result_for must be a number of seconds of at least 0, "
                f"not {show_result_for!r}."
            )
        if show_result_for and not auto_advance:
            raise ValueError(
                "show_result_for needs auto_advance: a page that moves on from "
                "its own JavaScript decides itself how long to show the result."
            )
        # Set by the PlayLiveGame that the page is given to.
        self.play_id = None
        self.auto_advance = auto_advance
        self.show_result_for = show_result_for
        self.player_left_message = player_left_message
        self.no_game_message = no_game_message
        self.too_late_message = too_late_message
        self.waiting_status = waiting_status
        self.ended_status = ended_status
        self.names = names
        self.player_info = player_info

    def check_ready_for_response(self, experiment, participant):
        _check_reached_game(participant, self._play_id())
        session_id = _live_game_id(participant, self._play_id())
        if session_id is None:
            return None
        # A player whose own game ended before the game did, or who came too
        # late, has their result.
        if _done_reason(session_id, participant.id) is not None:
            return None
        game = LiveGameRecord(session_id)
        status = game.status
        if status == LiveGameStatus.FAILED:
            raise LiveGameFailed(game)
        if status != LiveGameStatus.RUNNING:
            return None
        _check_session_can_still_end(session_id)
        _p = get_translator(context=True)
        return ResponseNotReady(
            _p(
                "live_game",
                "The game isn't over yet. The page will move on once it is.",
            ),
            retry_after=_RETRY_AFTER,
        )

    def ends_by(self, experiment, participant):
        session_id = _live_game_id(participant, self._play_id())
        if session_id is None or _done_reason(session_id, participant.id) == TOO_LATE:
            return None
        ends = _game_page_deadline(session_id)
        ended = _session_columns(session_id, "end_time").end_time
        if ended is not None and (ends is None or ended < ends):
            ends = ended
        if ends is None:
            return None
        return ends + timedelta(seconds=self.show_result_for)

    def validate(self, response, participant, **kwargs):
        # check_ready_for_response has already seen the player's game end,
        # and neither a player's saved ending nor an ended game's row
        # changes, so this result is final.
        session_id = _live_game_id(participant, self._play_id())
        if session_id is None:
            response.answer = None
            return None
        # None for a player added to a game that ended before it could add
        # them.
        response.answer = _computed_answer(session_id, participant.id)
        _set_live_game_answer(participant, self._play_id(), response.answer)
        return None

    def _play_id(self):
        if self.play_id is None:
            raise TypeError(
                "A LiveGamePage has to be the page of a "
                "PlayLiveGame, which starts the game the page plays."
            )
        return self.play_id

    def _check_page(self, page):
        if (
            page._validate_function is not None
            or type(page).validate is not ModularPage.validate
        ):
            raise TypeError(
                f"The game page {page.label!r} has a validate function of "
                "its own, which would replace the one that waits for the "
                "game's result. Remove the page's validate."
            )
        if page.time_limit is not None:
            raise TypeError(
                f"The game page {page.label!r} can't have a time_limit: a "
                "page that runs out of time skips the validate that saves the "
                "player's answer. Limit the game instead, with its duration "
                "or timeout."
            )

    def get_js_dependencies(self):
        return ["/static/scripts/live-game.js"]

    def get_js_page_code(self):
        return ["return PsyNetLiveGame.activatePage(psynet);"]

    def get_participant_page_config(self, experiment, participant):
        _check_reached_game(participant, self._play_id())
        session_id = _live_game_id(participant, self._play_id())
        _p = get_translator(context=True)
        player_left = self.player_left_message
        if player_left is _DEFAULT:
            player_left = _p("live_game", "Another player has left the game.")
        no_session = self.no_game_message
        if no_session is _DEFAULT:
            no_session = _p("live_game", "Your group couldn't start the game.")
        if session_id is None and _removed_from_group_notice(participant):
            # The page already shows why the participant's group left them.
            no_session = None
        too_late = self.too_late_message
        if too_late is _DEFAULT:
            too_late = _p(
                "live_game", "The game had already stopped taking new players."
            )
        if (
            session_id is not None
            and _done_reason(session_id, participant.id) == TOO_LATE
        ):
            # Known to have come too late, so the page shows no game.
            session_id, no_session = None, too_late
        waiting = self.waiting_status
        if waiting is _DEFAULT:
            waiting = _p("live_game", "Waiting for the other players to open the game")
        ended = self.ended_status
        if ended is _DEFAULT:
            ended = _p("live_game", "The game is over.")
        return {
            "liveGame": {
                "playId": self.play_id,
                "liveGameId": session_id,
                "gameChannel": (
                    None if session_id is None else _session_channel(session_id)
                ),
                "autoAdvance": self.auto_advance,
                "showResultFor": self.show_result_for,
                "playerLeftMessage": player_left,
                "noGameMessage": no_session,
                "tooLateMessage": too_late,
                "waitingStatus": waiting,
                "endedStatus": ended,
                "players": _players(participant, self._play_id()),
            }
        }


class LiveGamePage(ModularPage):
    """A game page: your own HTML and JavaScript module, which plays the
    group's game. Give it to a :class:`PlayLiveGame` as its ``page``.

    ::

        LiveGamePage(
            "rock_paper_scissors",
            tags.div(tags.h4(id="status"), ...),
            module="/static/rock-paper-scissors.js",
            waiting_status="Waiting for your partner",
            time_estimate=60,
        )

    The page's answer is what the game's :meth:`~LiveGame.answer` returns
    for the participant, once the game's result is saved. If the game fails,
    the page raises :class:`LiveGameFailed`. The page can't have a
    ``validate`` or a ``time_limit`` of its own. :ref:`live-games-page`
    explains how to write the page's JavaScript, and
    :ref:`live-games-cases` when the page moves on.

    Parameters
    ----------

    label
        The page's label.

    html
        What the page shows: HTML as a string, a ``dominate`` tag or a list
        of these, with the ``id`` of each element that the page's JavaScript
        finds.

    module
        URL of the JavaScript module that plays the game on the page; see
        :ref:`live-games-page`. To load other code, import it from this
        module or list it in ``js_dependencies``.

    auto_advance
        Whether the page moves on by itself once the game's result is
        saved, with its Next button hidden until then. Set it to ``False``
        to move on from the page's JavaScript instead.

    show_result_for
        Seconds the page stays once the game's result is saved, before
        it moves on by itself, so that its JavaScript can show the result.
        Default: 0. Needs ``auto_advance``.

    player_left_message
        What a notice at the top of the page says while another player has
        left the game page and not come back, or, once the game has started
        without them, hasn't opened it yet. By default it says "Another
        player has left the game." Set it to ``None`` for no notice.

    no_game_message
        What a notice at the top of the page says to a participant whose
        group didn't start a game, or, once it has ended, to a player whose
        game too few players were ready for, which never started. By
        default it says "Your group couldn't start the game." Set it to
        ``None`` for no notice. It isn't shown when the page already says
        that the participant's group left them.

    too_late_message
        What a notice at the top of the page says to a participant who
        joined a running game after its :meth:`~LiveGame.accepts_players`
        returned ``False``, or as it ended, in place of the game, with the
        Next button (see :ref:`live-games-joining`). By default it says "The game had already
        stopped taking new players." Set it to ``None`` for no notice.

    waiting_status
        What ``psynet.liveGame.showStatus`` says before the game starts. By
        default it says "Waiting for the other players to open the game".

    ended_status
        What ``psynet.liveGame.showStatus`` says once the player's game has
        ended. By default it says "The game is over."

    names
        How the page shows the other players, through
        ``psynet.liveGame.players``: ``"shown"``, the default, by their
        pseudonym, such as "Pink koala", or ``"anonymous"``, all as the same
        neutral figure, without sending the page the others' pseudonyms
        (see :ref:`live-games-whos-who`).

    player_info
        Optional function of the participant that returns what the pages
        show about them as a player, such as the avatar they chose, as any
        value that can be saved as JSON. It's called when the participant
        reaches the :class:`PlayLiveGame`, and each player's value is their
        ``info`` in ``psynet.liveGame.players``. An anonymous page gets only
        the participant's own.

    **kwargs
        Any other parameter of :class:`~psynet.modular_page.ModularPage`,
        such as ``css_links``, ``page_config`` and ``time_estimate``.
    """

    def __init__(
        self,
        label,
        html,
        module,
        *,
        auto_advance=True,
        show_result_for=0,
        player_left_message=_DEFAULT,
        no_game_message=_DEFAULT,
        too_late_message=_DEFAULT,
        waiting_status=_DEFAULT,
        ended_status=_DEFAULT,
        names="shown",
        player_info=None,
        **kwargs,
    ):
        html = _authored_html(type(self).__name__, html, kwargs)
        super().__init__(
            label,
            Prompt(tags.div(raw(html), data_live_game=True)),
            LiveGameControl(
                auto_advance=auto_advance,
                show_result_for=show_result_for,
                player_left_message=player_left_message,
                no_game_message=no_game_message,
                too_late_message=too_late_message,
                waiting_status=waiting_status,
                ended_status=ended_status,
                names=names,
                player_info=player_info,
            ),
            js_page_modules=[module],
            **kwargs,
        )


def _latest_end_seconds(session_id):
    # Seconds after its start by which a game has ended and saved its
    # result, or None for a game without a max_duration.
    max_duration = _session_game_class(session_id).max_duration
    return None if max_duration is None else max_duration + _SAVING_MARGIN


def _game_page_deadline(session_id):
    """Return when a game's page ends at the latest, or None for a
    game without a max_duration."""
    latest = _latest_end_seconds(session_id)
    if latest is None:
        return None
    return _session_began_at(session_id) + timedelta(seconds=latest)


def _session_began_at(session_id):
    # Dallinger's start_time: when the wait at the PlayLiveGame ended, before
    # the ready step.
    return _session_columns(session_id, "start_time").start_time


def _check_session_can_still_end(session_id):
    latest = _latest_end_seconds(session_id)
    if latest is None:
        return
    running_for = (timenow() - _session_began_at(session_id)).total_seconds()
    if running_for > latest:
        raise RuntimeError(
            f"Live game {session_id} is still running after "
            f"{running_for:.0f} seconds, though it should have ended by "
            f"{latest - _SAVING_MARGIN:g}, so its game page can't move on. "
            "The worker that runs the "
            "experiment's live games has probably stopped."
        )


def _players(participant, play_id):
    """Return how the participant's game page shows each player of their
    latest game at the PlayLiveGame ``play_id``, in player order: the
    player's pseudonym and the ``info`` that the page's ``player_info``
    gave, unless the page is anonymous, and whether it's the participant.
    Pages read it as ``psynet.liveGame.players``."""
    from ..participant import Participant
    from ..pseudonym import anonymous_sticker_html
    from .play import _live_game_data, _player_info

    data = _live_game_data(participant).get(play_id) or {}
    game_id = data.get("id")
    if game_id is None:
        return []
    if _done_reason(game_id, participant.id) == TOO_LATE:
        # The game never saw them, so their page shows no game.
        return []
    anonymous = data.get("names") == "anonymous"
    # Those who came too late are numbered last, so leaving them out keeps
    # the others' numbers.
    too_late = _too_late_players(game_id)
    participant_ids = [
        participant_id
        for participant_id in _session_participant_ids(game_id)
        if participant_id not in too_late
    ]
    if participant.id not in participant_ids:
        # Added to a running game, so not in its row until the addition is
        # written; the page asks again once its views show more players.
        participant_ids = [*participant_ids, participant.id]
    shown = {
        member.id: member
        for member in Participant.query.filter(Participant.id.in_(participant_ids))
    }
    _p = get_translator(context=True)
    players = []
    for participant_id in participant_ids:
        you = participant_id == participant.id
        if anonymous or participant_id not in shown:
            player = {
                "name": None,
                "css_color": None,
                "emoji": None,
                "sticker_html": str(anonymous_sticker_html()),
            }
            # As GroupPrompt and chat rooms label an anonymous member.
            label = (
                _p("live_game", "Your partner")
                if len(participant_ids) == 2
                else _p("live_game", "Another player")
            )
        else:
            player = shown[participant_id].pseudonym.to_dict()
            del player["color"], player["animal"]
            label = player["name"]
        player["you"] = you
        player["label"] = _p("live_game", "You") if you else label
        shows_info = (you or not anonymous) and participant_id in shown
        player["info"] = (
            _player_info(shown[participant_id], play_id) if shows_info else None
        )
        players.append(player)
    return players


def _players_payload(unique_id, play_id):
    """Return the participant's game page's players, for
    GET /live_game/players."""
    from ..participant import Participant

    participant = Participant.query.filter_by(unique_id=unique_id).one_or_none()
    if participant is None or play_id is None:
        return {"players": []}
    return {"players": _players(participant, play_id)}
