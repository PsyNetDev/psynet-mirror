.. _tests:

========================
Testing experiment logic
========================

Writing automated tests is an essential part of writing reliable software.
Automated tests are scripts that check the functionality of your program
and verify that it is working correctly.
PsyNet provides easy-to-use tools for writing tests for your own
experiment implementations; we recommend you use them whenever
designing your own experiment.

Built-in tests
--------------

All the demos in the PsyNet package are set up already with simple
automated tests. For this tutorial, we recommend you open up the
``static_audio`` demo to see how this is done.

The convention is for PsyNet experiment directories to contain a
single ``test.py`` file. This ``test.py`` file does not typically
contain any experiment-specific code; every demo has the same file.
This file uses the ``pytest`` package to invoke a generic testing method
defined on the Experiment class.
You can run this test by navigating to the experiment directory
and entering the following in your command line:

::

    psynet test local

This command takes a few moments to start as it has to spin up a
PsyNet local server. Once the server is ready,
the ``Experiment.test_serial_run_bots`` method is called.
This creates one or more 'bots', or virtual participants;
these bots progress through the experiment one page at a time.
Once the bots all reach the end of the experiment, and all relevant
checks have passed, the test script concludes.
If an error occurs, then a traceback is printed, giving you a
chance to debug it.

The default behavior of ``test_serial_run_bots`` is to create
one bot and run it through the entire experiment, one page at a time.
Unless you tell it otherwise, the bot will generate a random plausible
response for most page types. For example, if the page asks for
a multiple-choice response, the bot will typically choose its response
at random. This behavior can be customized by setting the ``bot_response``
argument when a page is created, either to a fixed value that the
bot always returns (e.g. ``True``), or to a function that is invoked
each time the bot reaches that page.

The 'static audio' demo shows an example where audio is recorded
from a participant. In this case we set
``bot_response_media="example-bier.wav"`` within the
``AudioRecordControl``; this tells the test to use the ``example-bier.wav``
file as the bot's response in all cases.

.. code-block:: python

    AudioRecordControl(duration=3.0, bot_response_media="example-bier.wav")


Custom tests
------------

By default all the test does is check that the bot can get to the
end of the experiment without errors. However it's often sensible
to implement some additional checks to make sure that the state of
the experiment is as you expect it. One way of doing this
is to override the ``Experiment.test_check_bot`` method.
This method is run when the bot completes the experiment.
At this point you can run some custom code to check that the
bot has the right status. In the 'static audio' demo, ``test_check_bot``
is used to verify that the bot has taken the right number of trials.

.. code-block:: python

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == len(nodes)

These customizations are often enough for simple use cases.
However, it's possible to provide arbitrarily complex logic for these
tests. For an example of a complex test, have a look at the
"rock, paper, scissors" demo, which has multiple bots take the experiment
at the same time, and coordinates how they step through the experiment
together.

.. code-block:: python

    class Experiment(...):
        ...

        test_n_bots = 2

        def test_serial_run_bots(self, bots: List[BotDriver]):
            from psynet.page import WaitPage

            advance_past_wait_pages(bots)

            assert bots[0].current_page_label == "choose_action"
            bots[0].take_page(response="rock")
            assert bots[0].current_page_label == "wait"

            assert bots[1].current_page_label == "choose_action"
            bots[1].take_page(response="paper")

            advance_past_wait_pages(bots)

            assert bots[0].current_page_text == "You chose rock, your partner chose paper. You lost."
            assert bots[1].current_page_text == "You chose paper, your partner chose rock. You won!"

            bots[0].take_page()
            bots[1].take_page()
            advance_past_wait_pages(bots)

            bots[0].take_page(response="scissors")
            bots[1].take_page(response="paper")
            advance_past_wait_pages(bots)

            assert bots[0].current_page_text == "You chose scissors, your partner chose paper. You won!"
            assert bots[1].current_page_text == "You chose paper, your partner chose scissors. You lost."

            bots[0].take_page()
            bots[1].take_page()
            advance_past_wait_pages(bots)

            bots[0].take_page(response="scissors")
            bots[1].take_page(response="scissors")
            advance_past_wait_pages(bots)

            assert (
                bots[0].current_page_text
                == "You chose scissors, your partner chose scissors. You drew."
            ), (
                "A rare error sometimes occurs here. If you see it, please report it to Peter Harrison (pmcharrison) for "
                "further debugging."
            )
            assert (
                bots[1].current_page_text
                == "You chose scissors, your partner chose scissors. You drew."
            ), (
                "A rare error sometimes occurs here. If you see it, please report it to Peter Harrison (pmcharrison) for "
                "further debugging."
            )

            bots[0].take_page()
            bots[1].take_page()
            advance_past_wait_pages(bots)

            assert "That's the end!" in bots[0].current_page_text
            assert "That's the end!" in bots[1].current_page_text


Parallel testing
----------------

By default the PsyNet experiment test just sends one bot through the entire experiment.
It is possible however to send more bots through the same experiment, and to tell PsyNet
to run those bots through the experiment in parallel, to give a better simulation of
the load incurred by a real experiment.
To change the default behavior for a given experiment, you can set the relevant attributes
on the experiment class, like this:

.. code-block:: python

    class Experiment(...):
        ...

        test_n_bots = 5
        test_modes = ["parallel"]


Alternatively, you can set these options when you call ``psynet test``, for example by writing:

.. code-block:: shell

    psynet test local --n-bots 5 --parallel

.. note::

    Parallel testing checks that your experiment behaves correctly under some
    concurrency, but it isn't designed to measure how the server performs under
    sustained load. When you want detailed latency and throughput statistics
    (for example to size a server before recruiting), use the dedicated
    :ref:`testing experiment performance <performance_testing>` command instead.


Testing on remote servers
-------------------------

Sometimes it's useful to test an experiment on remote server to get a better idea of how the server will
cope with large numbers of participants. First you need to launch a debug experiment to the server:

.. code-block:: shell

    psynet debug ssh --app my-experiment

Then you invoke ``psynet test``, similar to before but with ``ssh`` instead of ``local``:

.. code-block:: shell

    psynet test ssh --app my-experiment --n-bots 5 --parallel


Front-end tests
---------------

``psynet test local`` runs bots. They catch errors in page instantiation,
code blocks, networks, and recorded answers. They do not render a browser
layout, so they cannot tell you whether a page scrolls, whether a control
sits behind the footer, or whether content is wider than the window.

Checking those things means driving a real browser, normally with Playwright,
and keeping the walk with the experiment as ``tests/participant-flow.spec.js``.
Every participant page exposes ``psynetLayout.check()``, which reports the
layout violations it can find on the page as rendered.

For the current recipe, including which viewports to check and how to wait for
a page to be ready, see the "Layout checks" section of
``.cursor/skills/psynet/playwright-testing/SKILL.md``, which
``psynet scripts update`` installs in your experiment directory.

