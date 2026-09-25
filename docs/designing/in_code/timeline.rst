Timelines in code
=================

This page shows how the ideas in :doc:`/designing/timeline` appear in
``experiment.py``. It is written for reading and reviewing code as much as for
writing it.

The timeline is the ``timeline`` attribute of the experiment class. Most
experiments build it in a ``get_timeline`` function:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        timeline = get_timeline()

The ``demos/features/timeline`` demo uses most of the constructs on this page.
Run it with ``psynet debug local`` from the demo directory and click through
while reading the code:

.. literalinclude:: ../../../demos/features/timeline/experiment.py
   :pyobject: get_timeline

What a timeline is made of
--------------------------

A page is constructed directly, with a ``time_estimate`` in seconds:

.. code-block:: python

    InfoPage("Welcome to the experiment!", time_estimate=5)

A :class:`~psynet.timeline.PageMaker` wraps a function that returns a page.
The function can ask for ``participant`` and ``experiment`` arguments:

.. code-block:: python

    PageMaker(
        lambda participant: InfoPage(f"You answered {participant.answer}."),
        time_estimate=5,
    )

A :class:`~psynet.timeline.CodeBlock` wraps a function that runs on the
server and returns nothing:

.. code-block:: python

    def assign_condition(participant):
        participant.var.set("condition", random.choice(["A", "B"]))

    CodeBlock(assign_condition)

If the function is slow, use :class:`~psynet.timeline.AsyncCodeBlock`
instead. It runs in a background process and shows the participant a waiting
page until it finishes. Trial makers are covered in :doc:`trials`.

Remembering things about a participant
--------------------------------------

Participant variables live in ``participant.var`` and experiment-wide
variables in ``experiment.var``. Outside a lambda you can assign directly;
inside a lambda, use ``set``:

.. code-block:: python

    participant.var.color = "red"
    CodeBlock(lambda participant: participant.var.set("color", "red"))

Use ``participant.var.get("score", default=0)`` when a variable may not be
set yet.

To store a page's answer in a variable, pass ``save_answer``:

.. code-block:: python

    ModularPage(
        "color",
        "What is your favorite color?",
        PushButtonControl(choices=["red", "green", "blue"]),
        time_estimate=10,
        save_answer="favorite_color",
    )

The most recent answer is also available as ``participant.answer``.

When code runs
--------------

Everything at the top level of ``get_timeline`` runs when a server process
imports ``experiment.py``. Each web and worker process imports it separately,
so a random draw here is not tied to a participant and may differ between
processes:

.. code-block:: python

    # Wrong: drawn at import time, not per participant
    InfoPage(f"Your number is {random.randint(0, 100)}", time_estimate=5)

Moving the draw into a page maker is also wrong, because page makers run
again when the page is refreshed. Draw in a code block and display in a page
maker:

.. code-block:: python

    CodeBlock(
        lambda participant: participant.var.set("number", random.randint(0, 100))
    ),
    PageMaker(
        lambda participant: InfoPage(f"Your number is {participant.var.number}"),
        time_estimate=5,
    ),

Branching and repetition
------------------------

Give each construct a distinct, descriptive label; nested for loops must use
different labels.

- :func:`~psynet.timeline.conditional` takes a label, a ``condition``
  function, and ``logic_if_true`` / ``logic_if_false``.
- :func:`~psynet.timeline.switch` takes a label, a function returning a key,
  and a dictionary mapping keys to logic.
- :func:`~psynet.timeline.while_loop` takes a label, a ``condition``, and
  ``logic``, plus ``expected_repetitions`` for time estimation.
- :func:`~psynet.timeline.for_loop` takes keyword arguments only: ``label``,
  ``iterate_over`` (a function returning the list for this participant), and
  ``logic`` (a function from one item to timeline logic). It also needs
  ``expected_repetitions``, and ``time_estimate_per_iteration`` when ``logic``
  is a function.

The worked example above uses all four.

Organizing a long timeline
--------------------------

A :class:`~psynet.timeline.Module` groups a named section. Module names, like
trial maker IDs, must be unique within the timeline:

.. code-block:: python

    practice = Module(
        "practice",
        InfoPage("First, some practice.", time_estimate=5),
        practice_trial_maker,
    )

:func:`~psynet.timeline.join` combines elements and lists of elements into one
sequence, so sections can be defined separately and assembled into the full
timeline:

.. code-block:: python

    instructions = join(
        InfoPage("In this experiment you will rate sounds.", time_estimate=5),
        InfoPage("Use headphones if you can.", time_estimate=5),
    )

    def get_timeline():
        return Timeline(consent, instructions, practice, main_task, questionnaire)

Ending the experiment early
---------------------------

:class:`~psynet.timeline.Timeline` appends a
:class:`~psynet.page.SuccessfulEndPage` automatically. To end early, place an
:class:`~psynet.page.UnsuccessfulEndPage` in the timeline, typically inside a
conditional:

.. code-block:: python

    conditional(
        "screening_result",
        condition=lambda participant: participant.var.passed_screening,
        logic_if_true=main_task,
        logic_if_false=UnsuccessfulEndPage(failure_tags=["screening"]),
    )

Successful, unsuccessful, and rejected-consent endings each have their own
branch of end logic, which you can replace with keyword arguments to
``Timeline``, for example ``Timeline(..., unsuccessful_end=MyEndLogic())``.
See :class:`~psynet.end.SuccessfulEndLogic` and
:class:`~psynet.end.UnsuccessfulEndLogic`.

Time estimates
--------------

- Pages and page makers take ``time_estimate`` in seconds.
- Pages returned by a trial's ``show_trial`` use the trial class's
  ``time_estimate``, multiplied by the trial maker's
  ``expected_trials_per_participant``.
- :func:`~psynet.timeline.while_loop` multiplies the estimate of its logic by
  ``expected_repetitions``.
- :func:`~psynet.timeline.for_loop` uses ``time_estimate_per_iteration`` and
  ``expected_repetitions``.

.. seealso::

   :doc:`/reference/api/timeline` in the API reference.
