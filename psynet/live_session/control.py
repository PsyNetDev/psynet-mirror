"""LiveSessionControl, the control that joins a game page to its session.

The control has the page load ``live-session.js``. Its page code creates
``psynet.liveSession`` and leaves the session when the participant leaves
the page. ``get_participant_js_vars`` gives the script the session's id and
channel each time the page renders. ``check_ready_for_response`` refuses the
page's response until the session's result is saved, and ``validate`` then
sets the answer to the outcome. The game pays its rewards itself, when the
session's ending is saved.
"""

from datetime import timedelta

from dallinger import db
from dallinger.models import RealtimeSession, timenow

from ..modular_page import ModularPage, NullControl
from ..timeline import ResponseNotReady
from ..utils import get_translator
from .barrier import _check_reached_barrier, live_session_id
from .messages import _game_channel, _session_game_type
from .result import live_session_result

# Seconds a page waits before resending a response refused because the
# session's result isn't saved yet.
_RETRY_AFTER = 1

# Seconds past its max_duration that a session may take to save its result.
# One still running after that will never end.
_SAVING_MARGIN = 60

# The default text of a notice, translated as the page renders.
_DEFAULT = object()


class LiveSessionControl(NullControl):
    """The part of a game page where the participant plays their group's
    live session. Give the page to a :class:`PlayLiveGame` as its ``page``,
    and list the JavaScript file that plays the game in the page's
    ``js_page_modules``, as :class:`PlayLiveGame` shows.

    PsyNet sets the page's answer to the session's outcome, once the
    session's ending is saved, which is also when it pays the game's
    :meth:`~LiveGame.performance_reward`. The page can't have a ``validate``
    of its own.
    :doc:`/code/multiplayer/live_sessions` explains how to write the page's
    JavaScript.

    Parameters
    ----------

    auto_advance
        Whether the page moves on by itself once the session's result is
        saved, with its Next button hidden until then. A participant
        without a session still sees the button, and so does one whose page
        has been disconnected for ten seconds. Set it to ``False`` to
        move on from the page's JavaScript instead.

    show_result_for
        Seconds the page stays once the session's result is saved, before
        it moves on by itself, so that its JavaScript can show the result,
        for example in ``onResultSaved``. A :class:`~psynet.sync.GroupBarrier`'s
        ``late_after`` counts from the end of these seconds, so it needn't
        cover them. Default: 0. Needs ``auto_advance``.

    player_left_message
        What a notice at the top of the page says while another player has
        left the game page and not come back, such as "Your partner has
        left." By default it says "Another player has left the game." Set it
        to ``None`` for no notice, for a page that shows this its own way.

    no_session_message
        What a notice at the top of the page says to a participant whose
        group didn't start a session, for example because they were removed
        from a group that took too long to arrive. By default it says "Your
        group couldn't start the game." Set it to ``None`` for no notice.

    **kwargs
        Any other parameter of :class:`~psynet.modular_page.Control`, such as
        ``show_next_button``.
    """

    def __init__(
        self,
        auto_advance=True,
        show_result_for=0,
        player_left_message=_DEFAULT,
        no_session_message=_DEFAULT,
        **kwargs,
    ):
        super().__init__(**kwargs)
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
        self.barrier_id = None
        self.auto_advance = auto_advance
        self.show_result_for = show_result_for
        self.player_left_message = player_left_message
        self.no_session_message = no_session_message

    def check_ready_for_response(self, experiment, participant):
        session_id = live_session_id(participant, self._barrier_id())
        if session_id is None or live_session_result(session_id) is not None:
            return None
        _check_session_can_still_end(session_id)
        _p = get_translator(context=True)
        return ResponseNotReady(
            _p(
                "live_session",
                "The game isn't over yet. The page will move on once it is.",
            ),
            retry_after=_RETRY_AFTER,
        )

    def ends_by(self, experiment, participant):
        session_id = live_session_id(participant, self._barrier_id())
        if session_id is None:
            return None
        ends = _game_page_deadline(session_id)
        ended = _session_end_time(session_id)
        if ended is not None and (ends is None or ended < ends):
            ends = ended
        if ends is None:
            return None
        return ends + timedelta(seconds=self.show_result_for)

    def validate(self, response, participant, **kwargs):
        # check_ready_for_response has already seen the session end, and an
        # ended session's row doesn't change, so this result is final.
        session_id = live_session_id(participant, self._barrier_id())
        if session_id is None:
            response.answer = None
            return None
        result = live_session_result(session_id)
        # A failed session has no outcome if its record couldn't be saved, or
        # if Dallinger couldn't get one from the game's outcome method.
        if result.status == "failed" and result.outcome is None:
            response.answer = None
        else:
            game = _session_game_type(session_id)()
            response.answer = game.answer(
                result.outcome, result.end_reason, str(participant.id)
            )
        return None

    def _barrier_id(self):
        if self.barrier_id is None:
            raise TypeError(
                "A page with a LiveSessionControl has to be the page of a "
                "PlayLiveGame, which starts the session the page plays."
            )
        return self.barrier_id

    def _check_page(self, page):
        if (
            page._validate_function is not None
            or type(page).validate is not ModularPage.validate
        ):
            raise TypeError(
                f"The page {page.label!r} has a LiveSessionControl and a "
                "validate function of its own, which would replace the "
                "control's. Remove the page's validate."
            )

    def get_js_dependencies(self):
        return ["/static/scripts/live-session.js"]

    def get_js_page_code(self):
        return ["return PsyNetLiveSession.activatePage(psynet);"]

    def get_participant_js_vars(self, experiment, participant):
        _check_reached_barrier(participant, self._barrier_id())
        session_id = live_session_id(participant, self._barrier_id())
        _p = get_translator(context=True)
        player_left = self.player_left_message
        if player_left is _DEFAULT:
            player_left = _p("live_session", "Another player has left the game.")
        no_session = self.no_session_message
        if no_session is _DEFAULT:
            no_session = _p("live_session", "Your group couldn't start the game.")
        return {
            "liveSession": {
                "barrierId": self.barrier_id,
                "sessionId": session_id,
                "gameChannel": (
                    None if session_id is None else _game_channel(session_id)
                ),
                "autoAdvance": self.auto_advance,
                "showResultFor": self.show_result_for,
                "playerLeftMessage": player_left,
                "noSessionMessage": no_session,
            }
        }


def _latest_end_seconds(session_id):
    # Seconds after its start by which a session has ended and saved its
    # result, or None for a game without a max_duration.
    max_duration = _session_game_type(session_id).max_duration
    return None if max_duration is None else max_duration + _SAVING_MARGIN


def _game_page_deadline(session_id):
    """Return when a session's game page ends at the latest, or None for a
    game without a max_duration."""
    latest = _latest_end_seconds(session_id)
    if latest is None:
        return None
    return _session_start_time(session_id) + timedelta(seconds=latest)


def _session_start_time(session_id):
    return (
        db.session.query(RealtimeSession.start_time).filter_by(id=session_id).scalar()
    )


def _session_end_time(session_id):
    return db.session.query(RealtimeSession.end_time).filter_by(id=session_id).scalar()


def _check_session_can_still_end(session_id):
    latest = _latest_end_seconds(session_id)
    if latest is None:
        return
    max_duration = _session_game_type(session_id).max_duration
    running_for = (timenow() - _session_start_time(session_id)).total_seconds()
    if running_for > latest:
        raise RuntimeError(
            f"Live session {session_id} is still running after "
            f"{running_for:.0f} seconds, though its game's max_duration is "
            f"{max_duration:g}, so its game page can't move on. The worker "
            "that runs the experiment's live sessions has probably stopped."
        )
