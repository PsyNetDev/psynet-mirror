Timelines
=========

The timeline determines the sequential logic of the experiment.
A timeline comprises a series of *timeline elements* that, by default, are
presented sequentially. For example, the following code displays a welcome
message to the participant, then displays them a randomly generated number:

.. code-block:: python

    import random
    from psynet.page import InfoPage
    from psynet.timeline import CodeBlock, PageMaker, Timeline

    Timeline(
        InfoPage("Welcome to the experiment!", time_estimate=5),

        CodeBlock(lambda participant: participant.var.set(
            "random_number",
            random.randint(0, 100),
        )),

        PageMaker(
            lambda participant: InfoPage(
                f"My random number is {participant.var.random_number}"
            ),
            time_estimate=5,
        ),
    )

We will now go through these different kinds of components in turn.

.. admonition:: Recommended starting demo
   :class: tip

   The companion demo for this chapter lives at ``demos/features/timeline/``.
   Together with ``demos/features/pages/`` it forms one of the most important
   pairs of demos for understanding the core of PsyNet: it shows how to chain
   pages, store state on the participant, branch with ``switch`` and
   ``conditional``, and iterate with ``while_loop`` and ``for_loop``, all in a
   single short experiment. Run it with
   ``cd demos/features/timeline && psynet debug local`` and keep
   ``experiment.py`` open alongside this chapter.

Timeline elements
-----------------

There are three main kinds of timeline elements:

* `Pages`_
* `Page makers`_
* `Code blocks`_


`Pages`_ display content to the participant.
`Page makers`_ produce pages dynamically based on the participant's state.
`Code blocks`_ contain server logic that is executed in between pages,
for example to assign the participant to a group or to save the participant's data.

Pages
~~~~~

Pages define the web page that is shown to the participant at a given
point in time, and have fixed content that is the same for all participants.
We covered them in detail in the previous chapter, :doc:`pages`.

.. note::

   PsyNet uses *in-place timeline transitions* by default: when the participant
   advances to the next page, PsyNet swaps the page content inside the existing
   browser document instead of reloading the whole page. This does not affect
   how you write ordinary timelines, but it does constrain custom page
   templates and custom front-end components. See
   :doc:`../tutorials/writing_custom_frontends` for the fragment-template
   contract they must follow.

Page makers
~~~~~~~~~~~

Ordinary pages in the timeline have fixed content that is shared between all participants.
Often, however, we want to present content that depends on the state of the current participant.
This is the purpose of page makers.
A page maker is defined by a function that is called when the participant accesses the page.
For example, a simple page maker might look like the following:

.. code-block:: python

    from psynet.timeline import PageMaker

    PageMaker(
        lambda participant: InfoPage(f"You answered {participant.answer}."),
        time_estimate=5,
    )

.. note::

    The ``answer`` attribute stores the answer that the participant gave to the previous page.

The page maker function may accept up to two arguments, ``participant`` and ``experiment``,
but it doesn't have to accept all of these. See :class:`~psynet.timeline.PageMaker`
for more details.

.. warning::

    The page maker function will be called more than once for a given page,
    including whenever the page is refreshed. It is important therefore that the code
    is **idempotent** -- calling it multiple times should have the same effect as calling
    it once. It is a bad idea to incorporate random functions in this code; instead,
    set the random value in a code block (see below).


Code blocks
~~~~~~~~~~~

Code blocks define code that is executed in between pages. They are defined in a similar
way to page makers, except they don't return a page. For example:

.. code-block:: python

    from psynet.timeline import CodeBlock

    CodeBlock(
        lambda participant: participant.var.set("score", 10),
    )

For multi-line functions, you can use a named function instead of a lambda:

.. code-block:: python

    def update_scores(participant):
        participant.var.set("score_1", 10)
        participant.var.set("score_2", 20)

    CodeBlock(update_scores)

By default, code blocks will be executed as part of serving the participant's HTTP request.
If the function takes a long time to execute, we recommend instead using an
:class:`~psynet.timeline.AsyncCodeBlock`;
the function will then be executed in a separate process, and the participant will be shown a
waiting page until the function has finished executing.

Storing state
~~~~~~~~~~~~~

Participant state
^^^^^^^^^^^^^^^^^

It is possible to store arbitrary participant-specific state in ``participant.var``.

.. code-block:: python

    participant.var.color = "red"
    participant.var.color  # "red"

If you want to store state in a code block's lambda function, you will have to use
``participant.var.set`` instead (lambdas aren't allowed to use the ``=`` operator).

.. code-block:: python

    CodeBlock(lambda participant: participant.var.set("color", "red"))

If you want to store an answer from a page, you can use the page's ``save_answer`` parameter:

.. code-block:: python

    from psynet.timeline import Timeline
    from psynet.modular_page import ModularPage, PushButtonControl

    Timeline(
        ModularPage(
            "color",
            "What is your favorite color?",
            PushButtonControl(choices=["red", "green", "blue"]),
            time_estimate=10,
            save_answer="favorite_color",
        ),
        PageMaker(
            lambda participant: InfoPage(
                f"Your favorite color is {participant.var.favorite_color}"
            ),
            time_estimate=5,
        ),
    )

Experiment state
^^^^^^^^^^^^^^^^

If you want to define a dynamic variable that is shared across the entire experiment,
you can use ``experiment.var``:

.. code-block:: python

    from psynet.timeline import CodeBlock

    CodeBlock(lambda experiment: experiment.var.set("random_number", random.randint(1, 10)))


Code execution
--------------

It's important to be clear on PsyNet's code execution model, because this can be the source of
subtle errors.

When the web server is launched, the ``experiment.py`` file is imported, meaning that all code
within it is executed. This execution only happens once for that server, no matter how many
participants are tested. This has implications for randomness. For example, if you write this:

.. code-block:: python

    # experiment.py

    import random
    import psynet.experiment
    from psynet.page import InfoPage
    from psynet.timeline import Timeline

    def get_timeline():
        return Timeline(
            InfoPage(
                f"My random number is {random.randint(0, 100)}",
                time_estimate=5,
            )
        )


    class Exp(psynet.experiment.Experiment):
        timeline = get_timeline()

then ``get_timeline()`` will be called exactly once (when ``experiment.py`` is imported).
As a result, ``random.randint`` will be called just once, and multiple participants may see the
same random number. To address this issue, you could write something like this:

.. code-block:: python

    def get_timeline():
        return Timeline(
            PageMaker(
                lambda: InfoPage(f"My random number is {random.randint(0, 100)}"),
                time_estimate=5,
            )
        )

However, a subtle problem with this is that page makers are called every time the page loads.
This means that, if the participant refreshes the page, they will see a different random value,
which may not be desirable either.

Instead, the best way to achieve this functionality is by combining a code block with a page maker:

.. code-block:: python

    def get_timeline():
        return Timeline(
            CodeBlock(
                lambda participant: participant.var.set(
                    "random_number",
                    random.randint(0, 100),
                )
            ),
            PageMaker(
                lambda participant: InfoPage(
                    f"My random number is {participant.var.random_number}",
                ),
                time_estimate=5,
            )
        )

This can all be summarized with the following principle:
data that is specific to a given participant should be set in code blocks and read in page makers.

Control logic
-------------

By default, participants proceed through timelines in serial order.
However, PsyNet provides various control constructs that enable more complex ordering logic.

Conditional
~~~~~~~~~~~

The :func:`~psynet.timeline.conditional` construct decides what timeline logic to administer based
on a boolean expression. For example:

.. code-block:: python

    from psynet.timeline import conditional
    from psynet.modular_page import ModularPage, PushButtonControl

    Timeline(
        ModularPage(
            "choose_page",
            "What page do you want to see next?",
            PushButtonControl(choices=["page_1", "page_2"]),
            save_answer="choose_page",
        ),
        conditional(
            "choose_page",
            lambda participant: participant.var.choose_page == "page_1",
            logic_if_true=page_1,
            logic_if_false=page_2,
        ),
    )

Switch
~~~~~~

The :func:`~psynet.timeline.switch` construct is a more advanced version of the conditional that
is useful for choosing between more than two options:

.. code-block:: python

    from psynet.timeline import switch
    from psynet.modular_page import ModularPage, PushButtonControl

    Timeline(
        ModularPage(
            "choose_page",
            "What page do you want to see next?",
            PushButtonControl(choices=["page_1", "page_2", "page_3"]),
            save_answer="choose_page",
        ),
        switch(
            "choose_page",
            lambda participant: participant.var.choose_page,
            {
                "page_1": page_1,
                "page_2": page_2,
                "page_3": page_3,
            },
        ),
    )

While loop
~~~~~~~~~~

:func:`~psynet.timeline.while_loop` repeatedly administers some logic while a given test condition
is satisfied. In the following example, the while loop continues until the score exceeds 5:

.. code-block:: python

    from psynet.timeline import conditional, join, while_loop

    while_loop(
        "my_loop",
        lambda participant: participant.var.get("score", default=0) <= 5,
        logic=join(
            CodeBlock(lambda participant: participant.var.set("score", random.randint(1, 10))),
            conditional(
                "feedback",
                lambda participant: participant.var.score <= 5,
                logic_if_true=InfoPage(
                    f"You scored {participant.var.score}, bad luck.", time_estimate=5
                ),
                logic_if_false=InfoPage(
                    f"You scored {participant.var.score}, well done!", time_estimate=5
                ),
            ),
        ),
        expected_repetitions=2,
    )

Note that we have to tell ``while_loop`` how many repetitions we expect on average, so that PsyNet
can know how much time to estimate for that part of the timeline.

For loop
~~~~~~~~

:func:`~psynet.timeline.for_loop` iterates over a list whose values are determined when the
participant reaches that part of the timeline. For example:

.. code-block:: python

    from psynet.timeline import Timeline, for_loop
    from psynet.modular_page import DropdownControl

    Timeline(
        ModularPage(
            "target_number",
            "What number would you like to count up to?",
            DropdownControl([1, 2, 3, 4, 5]),
            time_estimate=5,
            save_answer="target_number",
        ),
        for_loop(
            "counting",
            iterate_over=lambda participant: list(range(1, participant.var.target_number + 1)),
            logic=lambda x: InfoPage(str(x), time_estimate=5),
            time_estimate_per_iteration=5,
            expected_repetitions=3,
        ),
    )

Note that, similar to ``while_loop``, we need to specify the number of expected repetitions so that
PsyNet can estimate how long this part of the timeline will take.

Module
~~~~~~

:class:`~psynet.timeline.Module` objects are a tool for organizing timeline logic into discrete
units. In addition to promoting better code organization, modules provide some utilities for
tracking user progress through the experiment (for example in the ``Timeline`` tab in the
dashboard).

A module can be defined with code like the following:

.. code-block:: python

    from psynet.timeline import Module, PageMaker
    from psynet.modular_page import ModularPage, NumberControl

    weight_module = Module(
        "weight",
        ModularPage(
            "weight",
            "What is your weight in kg?",
            NumberControl(),
            time_estimate=5,
            save_answer="weight",
        ),
        PageMaker(
            lambda participant: InfoPage(
                f"Your weight is {participant.var.weight} kg."
            ),
            time_estimate=5,
        ),
    )

It can then be incorporated into the timeline just like any other timeline logic:

.. code-block:: python

    from psynet.timeline import Timeline

    Timeline(
        InfoPage("Welcome to the experiment!", time_estimate=5),
        weight_module,
    )

It's also possible to store assets in a module:

.. code-block:: python

    from psynet.asset import asset
    from psynet.modular_page import AudioPrompt, ModularPage

    audio_module = Module(
        "audio",
        PageMaker(
            lambda assets: ModularPage(
                "groovy",
                AudioPrompt(
                    assets["groovy"],
                ),
            ),
            time_estimate=10,
        ),
        assets={
            "groovy": asset("/Users/dave/music/groovy.mp3"),
        },
    )

Note that the module's assets can then be accessed by the :class:`~psynet.timeline.PageMaker`'s lambda function.

.. note::

    In this case, though, you could have equivalently placed ``groovy.mp3`` in ``static/``
    and then pointed :class:`~psynet.modular_page.AudioPrompt` to ``"static/groovy.mp3"``.
    As discussed elsewhere, this approach works well for one-off assets, but doesn't scale
    so well to large stimulus sets.


Ending a participant's experiment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:class:`~psynet.page.SuccessfulEndPage` and
:class:`~psynet.page.UnsuccessfulEndPage`
are special page types that end a participant's experiment.
They redirect the participant to a dedicated end-of-experiment branch
(see `Timeline branches`_ below).
The difference between them is twofold:
:class:`~psynet.page.SuccessfulEndPage` marks the participant
with ``complete=True`` and ``failed=False``,
whereas :class:`~psynet.page.UnsuccessfulEndPage` marks the participant
with ``complete=False`` and ``failed=True``.
In both cases the participant will be paid the amount that they have accumulated so far;
however, :class:`~psynet.page.UnsuccessfulEndPage` is typically used to terminate an experiment early,
when the participant has yet to accumulate much payment.


Timeline branches
~~~~~~~~~~~~~~~~~

The timeline is organised into named **branches**. The ``main`` branch is what
you define when you create a :class:`~psynet.timeline.Timeline`; the remaining
branches are created automatically and handle end-of-experiment logic:

* ``main``: the participant's normal path through the experiment.
* ``successful_end``: shown when the participant completes the experiment
  successfully (via :class:`~psynet.end.SuccessfulEndLogic`).
* ``unsuccessful_end``: shown when the participant fails
  (via :class:`~psynet.end.UnsuccessfulEndLogic`).
* ``rejected_consent``: shown when the participant rejects a consent form
  (via :class:`~psynet.end.RejectedConsentLogic`).

A :class:`~psynet.page.SuccessfulEndPage` is automatically appended to the
end of the ``main`` branch, so participants who complete the experiment
normally are redirected to the ``successful_end`` branch.
You can also place :class:`~psynet.page.UnsuccessfulEndPage` or
:class:`~psynet.page.RejectedConsentPage` elements anywhere in the ``main``
branch; these redirect the participant to the corresponding end branch.

You can customise the end branches by passing keyword arguments to
:class:`~psynet.timeline.Timeline`:

.. code-block:: python

    from psynet.timeline import Timeline

    Timeline(
        ...,
        unsuccessful_end=MyCustomEndLogic(),
    )

When :meth:`~psynet.participant.Participant.fail` is called on a participant,
PsyNet automatically redirects them to the ``unsuccessful_end`` branch. This
ensures that failed participants always see an appropriate end page, regardless
of where they are in the timeline.

The redirect works differently depending on context:

* From within the page-advance loop, for example from a
  :class:`~psynet.timeline.CodeBlock`, the redirect happens immediately.
* From a background process, for example a timeout or admin action, the redirect
  is queued via ``participant.pending_redirect`` and applied the next time the
  participant submits a response. That queued redirect is navigation only; the
  unfinished trial on screen has already been failed.

The redirect is skipped if the participant is already in an end branch or has
already completed the experiment. Unfinished trials are failed; completed
trials stay unless a performance check treats them as unusable. See
:doc:`Participant and trial failure <../tutorials/participant_and_trial_failure>`.


Time estimates
~~~~~~~~~~~~~~

It is considered good practice to pay online participants a fee that corresponds
approximately to a reasonable hourly wage, for example 10 GBP/hour.
PsyNet provides sophisticated functionality for applying such
payment schemes without rewarding participants to participate slowly.
When designing an experiment, the researcher must specify along with each
page a ``time_estimate`` argument, corresponding to the estimated time in seconds
that a participant should take to complete that portion of the experiment.
This ``time_estimate`` argument is used to construct a progress bar displaying
the participant's progress through the experiment and to determine the participant's
final payment.

.. note::

    If you want PsyNet not to display information about financial rewards to the participants,
    you can set ``display_reward = false`` in your experiment's ``config.txt``.


Combining elements
------------------

We normally define our timelines by defining a ``get_timeline`` function in ``experiment.py``
and then saving the output of this function in our experiment class (typically named ``Exp``).

.. code-block:: python

    # experiment.py

    import random
    import psynet.experiment
    from psynet.page import InfoPage
    from psynet.timeline import CodeBlock, PageMaker, Timeline

    def get_timeline():
        return Timeline(
            InfoPage("Welcome to the experiment!", time_estimate=5),

            CodeBlock(lambda participant: participant.var.set(
                "random_number",
                random.randint(0, 100),
            )),

            PageMaker(
                lambda participant: InfoPage(
                    f"My random number is {participant.var.random_number}"
                ),
                time_estimate=5,
            ),
        )

Once your experiment gets complicated, it's usually a good idea to build the timeline up
out of multiple intermediate objects. For example, you can write something like this:

.. code-block:: python

    import psynet.experiment
    from psynet.page import InfoPage
    from psynet.timeline import join

    instructions = join(
        InfoPage("First you will...", time_estimate=5),
        InfoPage("Then you will...", time_estimate=5),
    )

    debrief = join(
        InfoPage("In this experiment you...", time_estimate=5),
        InfoPage("Your results will be helpful for...", time_estimate=5),
    )

    def get_timeline():
        return join(
            instructions,
            debrief,
        )

    class Exp(psynet.experiment.Experiment):
        timeline = get_timeline()

Note the use of the :func:`~psynet.timeline.join` function to create and merge sequences of
timeline elements. When its arguments are all elements, ``join`` behaves like a Python list
constructor; when the arguments also include lists of elements, ``join`` merges these lists.
This makes it helpful for combining timeline logic, where different bits of logic often correspond
either to elements or to lists of elements.

Exercises
---------

Using automated testing
~~~~~~~~~~~~~~~~~~~~~~~

It can be time-consuming to test timeline logic once an experiment becomes long.
Ultimately, a certain amount of manual testing will always be necessary to give you confidence
in your implementation.
However, PsyNet does provide some useful tools that can help you detect and fix errors early.

One key tool is automated testing.
In particular, PsyNet provides a default automated testing routine for every experiment
where it simply runs a 'bot' participant from beginning to end and verifies that no errors occur.
You can instruct such a test to run using the following command:

.. code-block:: bash

    psynet test local

As naive as this test may be, it does catch a lot of basic implementation errors,
and it can do so much faster than running ``psynet debug local`` and manually clicking through the
experiment. Note however that it only tests the back-end logic, not the front-end.

**Exercise**: run ``psynet test local`` on the companion demo at
``demos/features/timeline/``, and then try it on one of the larger pipeline demos
(e.g. ``demos/pipelines/simple_rating``).

.. hint::

    ``psynet`` commands should be run from the experiment directory.

Using the debugger
~~~~~~~~~~~~~~~~~~

The debugger is an additional tool that complements the automated testing well.
The process is as follows: you import the ``debugger`` function from ``psynet``,
and then you call it inside the code you want to debug. For example:

.. code-block:: python

    from psynet import debugger

    Timeline(
        InfoPage("Welcome to the experiment!", time_estimate=5),

        CodeBlock(lambda participant: participant.var.set(
            "random_number",
            random.randint(0, 100),
        )),

        PageMaker(
            lambda participant: debugger(),
            time_estimate=5,
        ),
    )

Then run the experiment, either using ``psynet test local`` or ``psynet debug local``.
Once the ``debugger()`` call is hit you will see a notice in the console to press F5 to begin
debugging. This should drop you into VSCode's built-in debugger, allowing you to inspect the
current variables and execute code in the debug console.
This is a great way to improve your understanding of how your experiment is working.

**Exercise**: insert a ``debugger()`` call inside one of the demos and use it to explore the local
environment.

.. note::

    To use the PsyNet debugger in a VSCode/Cursor project, your repository needs to contain an
    appropriate ``.vscode/launch.json`` file. The PsyNet demos provide an example you can copy.

    If you aren't using VSCode or Cursor you can use a different debugger instead.
    Unfortunately standard IDE debuggers don't work out of the box because of the way that PsyNet
    uses subprocesses. However, PyCharm's Python debug server works well, as does
    `rpdb <https://pypi.org/project/rpdb/>`_ (which is platform agnostic).


Making a shopping game
~~~~~~~~~~~~~~~~~~~~~~

In this exercise your task is to design your own timeline that takes advantage of various control
features in PsyNet. Here's the proposal: make a timeline that simulates the experience of going to
the shop and buying some items. In particular, imagine you're a shop assistant asking the customer
what they want. You give them a choice of items, you ask the customer how many items they want, and
add these items to their virtual basket. You then loop round, asking them if they want to choose
any more items, and so on. These items should all accumulate in the basket. Once the participant
says they're done, tell them how much they need to pay.
