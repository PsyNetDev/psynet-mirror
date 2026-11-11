.. _tests:
.. _simulated_participants:
.. _practice_data:

=======================
Testing back-end logic
=======================

The back end is everything that runs on the server: the timeline, trial
makers, code blocks, and the data they store. PsyNet tests it by sending
simulated participants, or **bots**, through the experiment. A bot takes the
same pages through the same server as a real participant, but without a
browser.

Running the tests
-----------------

Every PsyNet experiment contains a ``test.py`` file, which is the same in
every experiment. To run it, enter the following in the experiment
directory:

.. code-block:: shell

    psynet test local

This starts a local server and sends one bot through the whole experiment,
one page at a time. The test passes if the bot reaches the end without
errors and every check passes; otherwise it prints a traceback. To send
more bots, set ``test_n_bots`` on the experiment class.

How bots answer
---------------

By default, a bot gives a valid answer to each page, such as a random choice
from the options or a number in the allowed range. Most built-in controls
submit these default answers as the browser would, so they pass through the
page's and the control's ``format_answer`` and are saved with the same type as
a participant's answer: a ``NumberControl`` bot answer is a number, and a
``RatingControl`` bot answer is the rating itself. The ``bot_response``
argument of a page or control overrides this, either with a fixed value or with a
function called each time a bot reaches the page. The function can take any
of these arguments, which PsyNet passes by name: ``bot`` (the
:class:`~psynet.bot.Bot`, also available as ``participant``), ``experiment``,
``page``, ``trial`` and ``trial_maker`` (the bot's current trial and its trial
maker, inside a trial maker), and, for a control's ``bot_response``,
``prompt``:

.. code-block:: python

    PushButtonControl(
        ["1", "2", "3"],
        bot_response=lambda trial: trial.definition["correct_answer"],
    )

Custom pages and controls answer bots through ``get_bot_response``. A plain
value, whether from ``bot_response`` or ``get_bot_response``, is saved as the
final answer without passing through ``format_answer``. ``None`` counts as a
plain value: ``bot_response=None`` makes bots answer ``None``, so leave
``bot_response`` unset to keep the default answer. To send the bot's
answer through ``format_answer`` like a browser response, return
:class:`~psynet.bot.BotResponse` with ``raw_answer``:

.. code-block:: python

    def get_bot_response(self, experiment, bot, page, prompt):
        return BotResponse(raw_answer="hello")

Pages that collect recordings need a sample file for bots to submit:

.. code-block:: python

    AudioRecordControl(duration=3.0, bot_response_media="example-bier.wav")

For practice data and power analysis, bot answers can come from a
**response model**: code, kept with the experiment, that generates answers
from assumptions about how participants behave (the
:doc:`/skills/participant-response-models` skill describes how to write
one). ``psynet audit simulate``
runs bots and saves their export in the audit. The export has the same
tables, columns and files as a real one, so the analysis can be written and
tested before data collection, and it should recover the effects built into
the response model.

Adding checks
-------------

``Experiment.test_check_bot`` runs when a bot finishes the experiment and can
check its final state. For example, the ``static_audio`` demo checks that the
bot took one trial per node:

.. code-block:: python

    def test_check_bot(self, bot: Bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        assert len(bot.alive_trials) == len(nodes)

The base implementation asserts that the bot didn't fail, unless it
dropped out or the test said it may fail (see :ref:`bots_that_drop_out`).

PsyNet imports ``experiment.py`` before pytest starts, so a failed ``assert``
there reports only the line, not the values it compared. Give the assert a
message that shows them:

.. code-block:: python

    assert bot.current_page_text == "Round 2.", bot.current_page_text

To check something across all bots, such as how trials were shared between
them, override ``Experiment.test_check_bots``. It runs once after every bot
has finished, in serial and parallel mode, and receives the bots as
:class:`~psynet.bot.Bot` objects that can be queried like any other
database model. The base implementation calls ``test_check_bot`` for each
bot, so call ``super()`` to keep those checks. For example, the ``gibbs``
demo checks that the bots were split evenly between its two participant
groups:

.. code-block:: python

    def test_check_bots(self, bots: List[Bot]):
        assert len([b for b in bots if b.var.participant_group == "A"]) == 3
        assert len([b for b in bots if b.var.participant_group == "B"]) == 3
        super().test_check_bots(bots)

For finer control in serial mode (the default), override
``test_serial_run_bots``, which steps the bots
through the experiment. The ``rock_paper_scissors`` demo uses it to have two
bots play against each other and check each result:

.. code-block:: python

    class Experiment(...):
        test_n_bots = 2

        def test_serial_run_bots(self, bots: List[BotDriver]):
            advance_past_wait_pages(bots)

            bots[0].take_page(response="rock")
            bots[1].take_page(response="paper")
            advance_past_wait_pages(bots)

            assert "You chose rock, your partner chose paper. You lost." in bots[0].current_page_text
            assert "You chose paper, your partner chose rock. You won!" in bots[1].current_page_text

Each element of ``bots`` is a :class:`~psynet.bot.BotDriver`. Its methods and
properties, such as ``take_page``, ``current_page_label``,
``current_page_text`` and ``is_waiting`` (whether the bot is on a waiting
page, for example at a barrier), are documented under
:class:`~psynet.participant.ParticipantDriver`.

Bots that fail a prescreener
----------------------------

To test the path for participants who fail a prescreener, make some bots
answer it wrongly. :class:`~psynet.prescreen.HugginsHeadphoneTest` and
:class:`~psynet.prescreen.AntiphaseHeadphoneTest` answer wrongly when the bot
variable ``is_good_bot`` is ``False``. The ``headphone_test`` demo sets it in a
code block, where the participant ID is known, and checks the outcome:

.. literalinclude:: ../../demos/features/headphone_test/experiment.py
   :language: python
   :start-at: timeline = Timeline(
   :end-at: assert bot.failed
   :dedent: 4

Don't call ``super().test_check_bot`` for bots that are meant to fail: it
asserts that the bot didn't fail.

For other prescreeners, steer the bot through the prescreener's pages in
``test_serial_run_bots``, passing wrong answers to ``take_page``, then let
PsyNet finish the run:

.. code-block:: python

    def test_serial_run_bots(self, bots: List[BotDriver]):
        for bot in bots:
            if bot.id % 4 == 0:
                while bot.current_page_label != "color_vocabulary_trial":
                    bot.take_page()
                while bot.current_page_label == "color_vocabulary_trial":
                    bot.take_page(response="wrong")
            self.run_bot(bot, time_factor=self.test_time_factor)

``response`` is saved as the final answer, like a plain ``bot_response``
value. Find the page label and the answer format in the prescreener's source
code or in the ``response`` table of a previous test run.

.. _bots_that_drop_out:

Bots that drop out
------------------

In a group experiment, test what happens when a member leaves. Call
:meth:`~psynet.participant.ParticipantDriver.drop_out` for a participant who
returns the study on the recruitment platform, and stop taking pages for a
bot to simulate one who closes the tab, so that the barriers' timeouts deal
with them. Then check the others with ``bot.failed``, ``current_page_text``
and :attr:`~psynet.participant.ParticipantDriver.current_notice`, the notice
on their progress bar:

.. code-block:: python

    def test_serial_run_bots(self, bots: List[BotDriver]):
        quitter, stayer = bots
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots)

        quitter.drop_out()
        stayer.take_page()
        advance_past_wait_pages([stayer])
        assert stayer.current_notice == (
            "Your partner is no longer in your group. Please continue."
        )
        stayer.run_to_completion()

The default ``test_check_bot`` accepts bots that dropped out, but not others
that failed, such as a partner failed under the grouper's
``below_quorum="fail"``. Call
:meth:`~psynet.participant.ParticipantDriver.allow_failure` for those bots.
See :ref:`groups_below_min_size` for what happens to the members who stay.

Other helpers ask about a bot's group or act in it:

- :meth:`~psynet.participant.ParticipantDriver.with_participant` calls a
  function with the bot's participant, for example
  ``bot.with_participant(lambda p: p.current_trial.sync_group_role)`` for
  its role in the current round of a :class:`~psynet.sync.Regrouper`, or
  ``bot.with_participant(lambda p: p.sync_group_removal_reason("pair"))`` for
  why it left its pair.
- :meth:`~psynet.participant.ParticipantDriver.send_chat_message` posts a
  message to the :class:`~psynet.chatroom.ChatRoom` on the bot's current page.
- :meth:`~psynet.participant.ParticipantDriver.run_out_of_time` waits until
  the time limit of the bot's current page has passed and submits no answer,
  as a participant who leaves a timed page open does.
- :func:`~psynet.bot.bots_by_sync_group` sorts bots into their current groups
  of a type, for example ``for first, second in bots_by_sync_group(bots,
  "pair")``, since a grouper can pair them in any order.
- :func:`~psynet.bot.run_bots_to_completion` takes pages for several bots in
  turn until all have finished. Use it instead of ``run_to_completion`` on
  each bot while they still wait for each other, as players a
  :class:`~psynet.sync.Regrouper` keeps pairing do: one bot run to the end
  alone would wait at the next barrier for the others.
- :func:`~psynet.bot.regroup_now` makes a
  :class:`~psynet.sync.Regrouper` split the bots' pools as its ``deadline``
  or next ``every`` tick would, then advances them, so the test doesn't
  wait for it, for example ``regroup_now(bots[:3], pairing)`` to start a
  round without a fourth player who is still reading their results.
- :func:`~psynet.bot.make_late_now` makes the members who haven't reached a
  :class:`~psynet.sync.GroupBarrier` late, as its ``late_after`` would,
  then advances the bots waiting there, so a test of a player who goes
  quiet doesn't wait in real time, for example
  ``make_late_now(bots, "round_finished")`` after two of three players
  have answered.

When several groups play in one test, finish one group's story before driving
the next: a barrier's ``late_after`` clock keeps running for a group while the
test drives another, and a group still accepting top-ups takes the next bot
that reaches the grouper. A :class:`~psynet.sync.Regrouper` forms new groups at each
split and never dissolves them, so make a bot drop out before the split you
want it to miss.

.. _parallel_bot_tests:

Several bots at once
--------------------

To run several bots in parallel, set ``test_n_bots`` and ``test_mode`` on the
experiment class, or pass options on the command line:

.. code-block:: python

    class Experiment(...):
        test_n_bots = 5
        test_mode = "parallel"

.. code-block:: shell

    psynet test local --n-bots 5 --parallel

Parallel runs check that the experiment behaves correctly with several
participants at once. The bots run as threads in one process, so they share
module-level state and the experiment instance, including its timeline: store
per-bot traits on ``bot.var`` in ``initialize_bot`` rather than in globals or
on ``self``, and avoid calling ``random.seed()`` from experiment code. To
measure how the server performs under load, see :doc:`scalability`.

Testing on a remote server
--------------------------

To run the same test against a server, launch the experiment there in debug
mode, then call ``psynet test ssh`` (experimental):

.. code-block:: shell

    psynet debug ssh --app my-experiment
    psynet test ssh --app my-experiment --n-bots 5 --parallel

Like ``psynet performance-test ssh``, it uses the server's existing database;
see :ref:`performance_testing_server` for what that means for repeated runs.

Limitations
-----------

Bots don't display pages, so they don't detect layout problems or broken
browser behavior; see :doc:`frontend`. Bot answers are generated, not
collected from people, so simulated data can't show whether participants
understand the task or how they will respond.

.. seealso::

   The :doc:`/skills/simulate-participants` skill describes how to design and
   check simulated participants.
