from ..modular_page import NullControl
from .initializer import live_session_id
from .messages import _game_channel


class LiveSessionControl(NullControl):
    """The part of a page where the participant plays the session their
    group started at a :class:`LiveSessionInitializer`.

    Give it the initializer's id, and give the page a JavaScript file that
    plays the game, listed in its ``js_page_modules``:

    ::

        ModularPage(
            "rock_paper_scissors",
            Prompt(tags.div(tags.p(id="status"), ...)),
            LiveSessionControl("rock_paper_scissors"),
            js_page_modules=["/static/rock_paper_scissors.js"],
            time_estimate=30,
        )

    The JavaScript plays through ``psynet.liveSession``, which
    :doc:`/code/multiplayer/live_sessions` describes, with the cases a game
    page should allow for.

    Parameters
    ----------

    initializer_id
        The ``id_`` of the :class:`LiveSessionInitializer` that started the
        session.

    **kwargs
        Any other parameter of :class:`~psynet.modular_page.Control`, such as
        ``show_next_button``.
    """

    def __init__(self, initializer_id, **kwargs):
        super().__init__(**kwargs)
        self.initializer_id = initializer_id

    def get_render_js_vars(self, experiment, participant):
        session_id = live_session_id(participant, self.initializer_id)
        return {
            "liveSession": {
                "initializerId": self.initializer_id,
                "sessionId": session_id,
                "gameChannel": (
                    None if session_id is None else _game_channel(session_id)
                ),
            }
        }
