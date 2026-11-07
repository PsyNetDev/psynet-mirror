from ..modular_page import ModularPage, NullControl
from ..timeline import FailedValidation
from ..utils import get_translator
from .bonus import _add_bonus, _check_bonus
from .initializer import live_session_id
from .messages import _game_channel, _session_game_type
from .result import live_session_result

# Seconds a page waits before resending a response refused because the
# session's result isn't saved yet.
_RETRY_AFTER = 1


class LiveSessionControl(NullControl):
    """The part of a game page where the participant plays the live session
    their group started at a :class:`LiveSessionInitializer`.

    Give it the initializer's id, and list the JavaScript file that plays the
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
    game's :meth:`~LiveSession.bonus` when the participant leaves the page.
    The page can't have a ``validate`` of its own.
    :doc:`/code/multiplayer/live_sessions` explains how to write the page's
    JavaScript.

    Parameters
    ----------

    initializer_id
        The ``id_`` of the :class:`LiveSessionInitializer` that started the
        session.

    auto_advance
        Whether the page moves on by itself once the session's result is
        saved. Set it to ``False`` to move on from the page's JavaScript
        instead, for example after showing the result for a few seconds.

    **kwargs
        Any other parameter of :class:`~psynet.modular_page.Control`, such as
        ``show_next_button``.
    """

    def __init__(self, initializer_id, auto_advance=True, **kwargs):
        super().__init__(**kwargs)
        self.initializer_id = initializer_id
        self.auto_advance = auto_advance

    def check_ready_for_response(self, experiment, participant):
        session_id = live_session_id(participant, self.initializer_id)
        if session_id is None or live_session_result(session_id) is not None:
            return None
        _p = get_translator(context=True)
        return FailedValidation(
            _p("live_session", "Please wait while the game finishes..."),
            retry_after=_RETRY_AFTER,
        )

    def validate(self, response, participant, **kwargs):
        # check_ready_for_response has already seen the session end, and an
        # ended session's row doesn't change, so this result is final.
        session_id = live_session_id(participant, self.initializer_id)
        if session_id is None:
            response.answer = None
            return None
        result = live_session_result(session_id)
        response.answer = result.outcome
        paid = participant.live_session_bonuses_paid or []
        if result.record_complete and session_id not in paid:
            game = _session_game_type(session_id)()
            what = f"{type(game).__name__}.bonus"
            amount = game.bonus(result.outcome, result.end_reason, str(participant.id))
            _add_bonus(participant, _check_bonus(amount, what))
            participant.live_session_bonuses_paid = [*paid, session_id]
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

    def get_render_js_vars(self, experiment, participant):
        session_id = live_session_id(participant, self.initializer_id)
        return {
            "liveSession": {
                "initializerId": self.initializer_id,
                "sessionId": session_id,
                "gameChannel": (
                    None if session_id is None else _game_channel(session_id)
                ),
                "autoAdvance": self.auto_advance,
            }
        }
