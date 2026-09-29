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
from the options or a number in the allowed range. The ``bot_response``
argument of a page overrides this, either with a fixed value or with a
function called each time a bot reaches the page.

Custom pages and controls answer bots through ``get_bot_response``. A plain
value, whether from ``bot_response`` or ``get_bot_response``, is saved as the
final answer without passing through ``format_answer``. To send the bot's
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

The base implementation asserts that the bot didn't fail.

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
participants at once. To measure how the server performs under load, see
:doc:`scalability`.

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
