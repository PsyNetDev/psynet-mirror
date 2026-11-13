"""LiveSessionControl, the control that joins a game page to its session.

The control has the page load ``live-session.js``. Its page code creates
``psynet.liveSession`` and leaves the session when the participant leaves
the page. ``get_participant_js_vars`` gives the script the session's id and
channel each time the page renders. ``check_ready_for_response`` refuses the
page's response until the session's result is saved, and ``validate`` then
sets the answer to the outcome and pays the outcome reward once per session.
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
from .reward import _add_reward, _check_reward

# Seconds a page waits before resending a response refused because the
# session's result isn't saved yet.
_RETRY_AFTER = 1

# Seconds past its max_duration that a session may take to save its result.
# One still running after that will never end.
_SAVING_MARGIN = 60

# The default text of a notice, translated as the page renders.
_DEFAULT = object()


class LiveSessionControl(NullControl):
    """The part of a game page where the participant plays the live session
    their group started at a :class:`LiveGameBarrier`.

    Give it the game barrier's id, and list the JavaScript file that plays the
    game in the page's ``js_page_modules``:

    ::

        ModularPage(
            "rock_paper_scissors",
            Prompt(tags.div(tags.p(id="status"), ...)),
            LiveSessionControl("rock_paper_scissors"),
            js_page_modules=["/static/rock_paper_scissors.js"],
            time_estimate=30,
        )

    PsyNet sets the page's answer to the session's outcome, and pays the
    game's :meth:`~LiveGame.performance_reward` when the participant leaves the page.
    The page can't have a ``validate`` of its own.
    :doc:`/code/multiplayer/live_sessions` explains how to write the page's
    JavaScript.

    Parameters
    ----------

    barrier_id
        The ``id_`` of the :class:`LiveGameBarrier` that started the
        session.

    auto_advance
        Whether the page moves on by itself once the session's result is
        saved, with its Next button hidden until then. A participant
        without a session still sees the button, and so does one whose page
        has been disconnected for ten seconds. Set it to ``False`` to
        move on from the page's JavaScript instead, for example after
        showing the result for a few seconds.

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
        barrier_id,
        auto_advance=True,
        player_left_message=_DEFAULT,
        no_session_message=_DEFAULT,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.barrier_id = barrier_id
        self.auto_advance = auto_advance
        self.player_left_message = player_left_message
        self.no_session_message = no_session_message

    def check_ready_for_response(self, experiment, participant):
        session_id = live_session_id(participant, self.barrier_id)
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
        session_id = live_session_id(participant, self.barrier_id)
        if session_id is None:
            return None
        latest = _latest_end_seconds(session_id)
        if latest is None:
            return None
        return _session_start_time(session_id) + timedelta(seconds=latest)

    def validate(self, response, participant, **kwargs):
        # check_ready_for_response has already seen the session end, and an
        # ended session's row doesn't change, so this result is final.
        session_id = live_session_id(participant, self.barrier_id)
        if session_id is None:
            response.answer = None
            return None
        result = live_session_result(session_id)
        response.answer = result.outcome
        paid = participant.live_session_rewards_paid or []
        # A failed session has no outcome if its record couldn't be saved, or
        # if Dallinger couldn't get one from the game's outcome method.
        has_outcome = result.status != "failed" or result.outcome is not None
        if has_outcome and session_id not in paid:
            game = _session_game_type(session_id)()
            what = f"{type(game).__name__}.performance_reward"
            amount = game.performance_reward(
                result.outcome, result.end_reason, str(participant.id)
            )
            _add_reward(participant, _check_reward(amount, what))
            participant.live_session_rewards_paid = [*paid, session_id]
        return None

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
        _check_reached_barrier(participant, self.barrier_id)
        session_id = live_session_id(participant, self.barrier_id)
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
                "playerLeftMessage": player_left,
                "noSessionMessage": no_session,
            }
        }


def _latest_end_seconds(session_id):
    # Seconds after its start by which a session has ended and saved its
    # result, or None for a game without a max_duration.
    max_duration = _session_game_type(session_id).max_duration
    return None if max_duration is None else max_duration + _SAVING_MARGIN


def _session_start_time(session_id):
    return (
        db.session.query(RealtimeSession.start_time).filter_by(id=session_id).scalar()
    )


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
