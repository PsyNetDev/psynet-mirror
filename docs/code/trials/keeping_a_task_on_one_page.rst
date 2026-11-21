Keeping a task on one page
==========================

A fast task can present many trials on a single page, while the trial maker
still assigns, scores and saves one trial per response. If you're still
deciding whether to do this, see :doc:`/design/presenting_trials`.

There are two ways to do it:

- **A prepared sequence.** A :class:`~psynet.trial.static.StaticTrialMaker`
  creates all of the participant's trials up front, and a
  :class:`~psynet.live_game.LiveTrialGame` presents them in order on one live
  game page. The browser can receive the upcoming stimuli in advance, so the
  next one appears as soon as the participant answers.
- **Ordinary trial pages.** The browser doesn't reload between pages: PsyNet
  swaps in the next page's content. Trial pages that share a layout and answer
  on a key press therefore already look like one page. This works with any
  trial maker, including adaptive ones such as staircases, where each answer
  decides what comes next. Each answer waits for the server to send the next
  trial's page.

.. _single-page-prepared:

A prepared sequence
-------------------

:download:`The arrow flanker demo <../../../demos/features/live_trial_game/experiment.py>`
is a complete example.

Use a :class:`~psynet.live_game.LiveTrialGame` inside a
:class:`~psynet.trial.static.StaticTrialMaker` whose ``node_order`` fixes each
participant's sequence. When the game starts, the maker creates the
participant's trials for the block, or reloads them if they already exist, and
the game presents them in order.

Answering trials
~~~~~~~~~~~~~~~~

Define the answer message by subclassing :class:`~psynet.live_game.TrialAnswer`
and narrowing the type of ``answer``. Register it in the game's ``messages``.
PsyNet checks each answer against that type, saves it on the current trial and
scores it with the trial's ``score_answer``::

    class BirdAnswer(TrialAnswer):
        answer: Literal["left", "right"]

    class BirdGame(LiveTrialGame):
        min_players = max_players = 1
        messages = [BirdAnswer]
        preload_fields = ("bird",)

In the page's JavaScript, start a response clock when you display a stimulus,
and answer through the handle it returns:

.. code-block:: javascript

    // When the stimulus appears:
    response = game.startResponseClock(view);
    // When the participant presses a key:
    response.answer("left");

The browser measures the response time from the call to
``startResponseClock`` to the call to ``answer``, and sends both with the
trial's position. The server checks that the position is still the current
one, so a late or duplicated answer can't land on the next trial, even when
the next trial shows the same stimulus. PsyNet stores the time in seconds in
the trial's ``time_taken``.

Start a new clock whenever you display a stimulus again, including after a
reload. Don't restart it when the server merely confirms the view you are
already showing. A handle sends at most one answer, so repeated key presses
are ignored. If the server rejects the answer, the same handle can send again.

If you need a custom message rather than :class:`~psynet.live_game.TrialAnswer`,
call ``game.answer_trial(state, player=player, answer=value, position=position)``
from its ``apply`` method, passing the zero-based position the player saw.

Sending stimuli ahead
~~~~~~~~~~~~~~~~~~~~~

By default, the browser receives only the current trial's ``definition``,
together with ``completed`` (the number answered), ``total`` and ``stop``. To
show the next stimulus without waiting for the server, set ``preload_fields``
to the definition keys the browser may see. The view then also contains a
``deck``: those fields for each trial up to ``stop``. The same fields are the
only ones sent for the current trial, so you can keep answer keys on the
server.

With a deck in the browser, opt into showing the next trial straight away by
calling ``game.predict(game.predictTrialAnswer)``. Both the arrow and bird demos
do this. Without a deck, leave out the prediction and render each new view
from ``game.onChange``.

To send something other than the stored definition, such as the URL of a
node's image asset, override ``StaticTrialMaker.get_public_definition(trial)``.
A URL alone doesn't download the image. For a small fixed set of images,
declare them in the page's :class:`~psynet.timeline.MediaSpec`, as in the
``features/live_trial_game_images`` demo. For a long or participant-specific
set, have your page's JavaScript fetch the next few images from the deck while
the participant answers, and wait for each image's ``decode()`` before showing
it and starting its response clock.

Splitting a sequence into parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To stop partway through, for example to show feedback, pass
``settings={"stop": 25}``. The game then ends after the trial at position 24,
because ``stop`` is exclusive and counts from zero. A later ``PlayLiveGame``
step, with its own ``id_``, continues from the first unanswered trial. Leave
out ``stop`` to finish the sequence.

For example, to play the first 25 trials and run the trial maker's
performance check before the rest::

    def present_trials(self):
        return join(
            PlayLiveGame(
                id_="first_half",
                game_class=SortingGame,
                settings={"stop": 25},
                page=make_sorting_page(),
            ),
            self.check_performance(),
            PlayLiveGame(
                id_="second_half", game_class=SortingGame, page=make_sorting_page()
            ),
        )

Each ``PlayLiveGame`` needs a page object of its own, so ``make_sorting_page``
here builds a new :class:`~psynet.live_game.LiveGamePage` each time.

Interruptions and timeouts
~~~~~~~~~~~~~~~~~~~~~~~~~~

A one-player game picks up where the participant left off. If the game ends
early because the participant left, failed to join or reached the game's
timeout, PsyNet starts a new game on the same unanswered trial when they
return.

Each trial's response timeout starts when the game presents the trial, and
doesn't restart after an interruption. As on an ordinary trial page, a trial
that isn't answered within the trial maker's ``response_timeout_sec`` fails,
but the participant carries on: when they answer, PsyNet stores the answer,
the trial stays failed and the game moves to the next trial. Set
``response_timeout_sec=None`` to turn the timeout off.

Reading the results
~~~~~~~~~~~~~~~~~~~

The responses are on the trials, as for any trial maker: each has its
``definition``, ``answer``, ``score`` and ``time_taken``. To read a
participant's responses across several games in the same trial maker, query
completed trials by ``module_state_id``. The game's own outcome, and the
page's answer, are empty dictionaries. Override
:meth:`~psynet.live_game.LiveGame.outcome` if the game also produces a joint
result, such as a team payoff.

.. _single-page-trial-pages:

Ordinary trial pages
--------------------

:download:`The adaptive brightness demo <../../../demos/features/staircase_on_one_page/experiment.py>`
is a complete example. It runs a staircase with PsyNet's
:class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker`.

Write ``show_trial`` as usual. Give every trial's page the same HTML, and put
the data that changes from trial to trial in the page's ``contents``::

    def show_trial(self, experiment, participant):
        return ModularPage(
            "contrast",
            patches_html,
            contents={"left": self.definition["left"], "right": self.definition["right"]},
            show_next_button=False,
            js_page_modules=["/static/contrast.js"],
            bot_response=...,
            time_estimate=self.time_estimate,
        )

When the participant answers, PsyNet completes the trial and the trial maker
chooses the next one, as on any trial page. The browser then swaps in the next
trial's page without reloading, and because the layout is the same, only the
stimulus appears to change. PsyNet runs your page module's ``activate``
function for each trial's page, so draw the trial there and answer on a key
press instead of a Next button:

.. code-block:: javascript

    export function activate({root, psynet}) {
        const pair = psynet.page.contents;
        // Draw the pair.
        function keydown(event) {
            // On the left arrow key: psynet.nextPage("left");
        }
        document.addEventListener("keydown", keydown);
        return () => document.removeEventListener("keydown", keydown);
    }

The function that ``activate`` returns runs before the next page replaces this
one, so listeners on ``document`` don't pile up. The trial's ``time_taken`` is
measured in the browser, from when the page has been set up to when
``psynet.nextPage`` is called.
