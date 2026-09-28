Writing a timeline
==================

This page shows how the ideas in :doc:`/design/timeline` appear in
``experiment.py``.

The timeline is the ``timeline`` attribute of the experiment class. Most
experiments build it in a ``get_timeline`` function:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        timeline = get_timeline()

The ``demos/features/timeline`` demo uses most of the constructs on this page.
Run it with ``psynet debug local`` from the demo directory and click through
while reading the code:

.. literalinclude:: ../../demos/features/timeline/experiment.py
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
page until it finishes. It needs a named function (lambdas raise an error)
and an ``expected_wait`` in seconds:

.. code-block:: python

    def prepare_stimuli(participant):
        ...

    AsyncCodeBlock(prepare_stimuli, expected_wait=10)

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

Experiment variables
--------------------

Experiment variables are shared by all participants. Declare them, with their
initial values, in the experiment class's ``variables`` dictionary:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        variables = {
            "max_participant_payment": 10.0,  # overrides a default
            "difficulty": 1,  # a new variable
        }

PsyNet's built-in variables, such as ``max_participant_payment``, have
defaults that entries here override; see
:class:`~psynet.experiment.Experiment` for the list. Read them with
``experiment.var.difficulty`` and change them during the experiment with
``set``:

.. code-block:: python

    CodeBlock(lambda experiment: experiment.var.set("difficulty", 2))

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

.. _pre_deploy_routines:

Pre-deploy routines
-------------------

A :class:`~psynet.timeline.PreDeployRoutine` runs a function once, on the
machine that launches the experiment, before the experiment starts. It takes
a label, the function, and a dictionary of keyword arguments for the function.
It can go anywhere in the timeline, any number of times, and shows nothing to
participants. This one configures an Amazon S3 bucket:

.. code-block:: python

    from psynet.media import setup_bucket_for_presigned_urls
    from psynet.timeline import PreDeployRoutine

    PreDeployRoutine(
        "setup_bucket_for_presigned_urls",
        setup_bucket_for_presigned_urls,
        {"bucket_name": "recordings_s3_bucket", "public_read": True},
    )

The function can also take an ``experiment`` argument. Database changes it
makes are carried into the launched experiment, so it suits database setup
tasks. Assets it deposits count as prepared before launch and are left out of
``psynet export``.

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
  ``logic`` (a function from one item to timeline logic). It needs
  ``time_estimate_per_iteration`` when ``logic`` is a function, and
  ``expected_repetitions`` when ``iterate_over`` takes arguments such as
  ``participant``.

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

.. _writing_a_timeline_ending_early:

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
