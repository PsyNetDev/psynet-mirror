Keeping a task on one page
==========================

To present several trials on a single page, put a live game in your trial
maker's ``present_trials()`` timeline. The maker assigns and records the
trials. Your page draws each stimulus and sends the participant's answer.
If you're still choosing how to present the task, see
:doc:`/design/presenting_trials`.

.. _single-page-prepared:

Presenting prepared static trials
---------------------------------

Use :class:`~psynet.live_game.LiveTrialGame` when each player has a fixed
sequence from a :class:`~psynet.trial.static.StaticTrialMaker`. Put the
:class:`~psynet.live_game.PlayLiveGame` step inside the maker's
``present_trials()`` timeline. When the group starts, PsyNet prepares or
reloads the native trials for each player in seat order.

Set ``settings={"stop": 25}`` to play up to position 25 (exclusive).
A second step with its own game ID can omit ``stop`` to finish the full deck.
Each session starts at the first unanswered item. The default view supplies
the player's current ``definition``, number ``completed``, ``total`` and
``stop``. To send trial definitions up front, set ``preload_fields`` to the
public keys of each definition. The view then includes a ``deck`` up to the
segment boundary and applies the same field selection to the current item.
Override ``StaticTrialMaker.get_public_definition(trial)`` to present a
different representation, such as the URL of a node's image asset. Sending a URL
does not fetch the image. Declare a small fixed set of page images using
:class:`~psynet.timeline.MediaSpec` as in the ``features/live_trial_game_images``
bird direction demo, or start fetching upcoming images from
the deck in your browser module as VocabTest does.

For ordinary answers, subclass :class:`~psynet.live_game.TrialAnswer` and
register the message in the game. PsyNet validates the answer and submits it
to the current native trial, where ``score_answer`` can score it::

    class BirdAnswer(TrialAnswer):
        answer: Literal["left", "right"]

    class BirdGame(LiveTrialGame):
        messages = [BirdAnswer]
        preload_fields = ("bird",)

The browser starts a local clock when the experiment displays an occurrence.
Keep the handle until the participant answers. For example, these lines belong
in the display and input handlers respectively:

.. code-block:: javascript

    response = game.startResponseClock(view);
    // On the participant's keypress:
    response.answer("left");

The handle captures the position and sends ``trial_answer`` with ``position``,
``answer`` and browser-measured ``seconds``. Starting it sends no message.
Start a fresh clock on redisplay, including after reload. Preserve the existing
clock when a new server view merely confirms the same presentation. A queued
answer suppresses duplicate input. A refused send or server rejection lets the
current handle retry. The server checks the position and computes the score.

Both the arrow and bird demos explicitly opt into local prediction with
``game.predict(game.predictTrialAnswer)``. With a public deck, the next item
can appear immediately. With only a current definition, omit prediction and
render the next server view via ``game.onChange``. The clock needs only the
current definition and position. The prepared trial maker still selects the
server-side sequence up front.

A custom :class:`~psynet.live_game.LiveMessage` can call
``game.answer_trial(state, player=player, answer=value, position=position)``.
Passing the zero-based position shown to the player rejects stale responses,
including when the next trial repeats the same stimulus. PsyNet opens the
first response clock, advances it after each saved answer and ends the session
when everyone reaches their boundary.

For a one-player game (both ``min_players`` and ``max_players`` are 1), omit
``group_type`` from ``PlayLiveGame``. This starts a session directly for the
participant. For example, the vocabulary screen plays a form and then
applies its trial maker's existing performance check::

    join(
        PlayLiveGame(
            id_="vocabulary_form_1",
            game_class=VocabularyGame,
            settings={"stop": 34},
            page=word_page,
        ),
        maker.check_performance(),
    )

A solo prepared segment advances when the required native trials are complete.
If the live session ends because the participant leaves, fails to join, or
reaches the session timeout, returning starts a session on the same open
trial. Its original ``response_started_at`` still applies. Expiry of the
maker's ``response_timeout_sec`` ends the segment as incomplete. Setting it
to ``None`` leaves the response window open. Normal participant exit and
failure rules still apply. Use ``maker.check_performance()`` in the timeline
to run the screening check after a completed form.

A browser can report each display (including a reload) via a message that
calls ``game.record_trial_presentation(state, player=player, position=position)``.
PsyNet then stores the observed display count in ``trial.var.n_presentations``.
VocabTest's ``time_taken`` is measured from the display on which the person
answered. Bots that supply an answer without displaying a word have no count.

Each player's native trials hold their definitions and answers. Query completed
trials by ``module_state_id`` to read responses across sessions in the same
trial-maker run. The default session outcome and page answer are both empty
dictionaries. Override :meth:`~psynet.live_game.LiveGame.outcome` if the game
also produces a joint result, such as a team payoff.


.. _single-page-on-demand:

On-demand trials on a solo game page
------------------------------------

Return a ``PlayLiveGame`` from the maker's ``present_trials()``, with a
:class:`~psynet.live_game.OnDemandTrialGame` subclass. Set its ``answer_type``
to a typed ``TrialAnswer`` and implement ``bot_answer(view)`` with that type.
In the page, subscribe with ``game.onTrial(render)`` and call
``game.startResponseClock(view)`` when the renderer presents the stimulus.
The same renderer can use ``onTrial`` for a prepared deck.

The active maker assigns one native trial at a time. Each answer is validated
and completed in the transaction that selects its successor. By default the
page receives the complete saved ``trial.definition``. A maker can override
``get_public_definition(trial)`` when presentation needs a different payload,
such as a vocabulary image URL with the scoring key kept on the server.
The runner manages presence and game ending. The page receives its private
assignment in the HTTP response, with no timeline transition. The
``features/live_trial_game_adaptive`` demo grows a within-participant chain with the
existing geometric staircase trial maker. This path supports independent solo selections with a single custom
renderer and synchronous scoring. Per-trial feedback, timeline controls and
per-trial performance-check pages require the ordinary trial timeline.
