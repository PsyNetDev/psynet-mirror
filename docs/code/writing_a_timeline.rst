Writing a timeline
==================

The timeline is the ``timeline`` attribute of the experiment class. Most
experiments build it in a ``get_timeline`` function:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        timeline = get_timeline()

Most examples on this page come from the ``demos/features/timeline`` demo.
Run it with ``psynet debug local`` from the demo directory to click through
them.

What a timeline is made of
--------------------------

The demo's timeline starts with four elements:

.. literalinclude:: ../../demos/features/timeline/experiment.py
   :start-after: return Timeline(
   :end-before: ModularPage(
   :dedent: 8

- A page, here a :class:`~psynet.modular_page.ModularPage`, is constructed
  directly, with a ``time_estimate`` in seconds.
- A :class:`~psynet.timeline.PageMaker` wraps a function that returns a page,
  so that the page can depend on the participant. The function can take
  ``participant`` and ``experiment`` arguments.
- A :class:`~psynet.timeline.CodeBlock` wraps a function that runs on the
  server and returns nothing.

A slow function goes in an :class:`~psynet.timeline.AsyncCodeBlock`, which
runs it in a background process. It needs a named function; lambdas raise an
error. With ``wait=True``, the default, the participant sees a waiting page
until the function finishes, and ``expected_wait`` in seconds is required.
With ``wait=False``, the participant carries on while the function runs. The
``demos/features/async_codeblock`` demo shows both:

.. literalinclude:: ../../demos/features/async_codeblock/experiment.py
   :start-at: def set_participant_var1
   :end-before: class Exp

.. literalinclude:: ../../demos/features/async_codeblock/experiment.py
   :start-at: timeline = Timeline(
   :end-before: def test_check_bot
   :dedent: 4

Remembering things about a participant
--------------------------------------

Participant variables live in ``participant.var``. Outside a lambda, assign
them directly; inside a lambda, use ``set``, because Python doesn't allow
assignments in lambdas:

.. code-block:: python

    participant.var.color = "red"
    CodeBlock(lambda participant: participant.var.set("color", "red"))

Use ``participant.var.get("score", default=0)`` when a variable may not be
set yet.

A page's answer is stored in a variable when the page is given
``save_answer``. In the demo above, the first page saves its answer as
``favorite_color``, and the page maker after it reads
``participant.var.favorite_color``. The most recent answer is also available
as ``participant.answer``.

Experiment variables are shared by all participants and live in
``experiment.var``. Declare them, with their initial values, in the
experiment class's ``variables`` dictionary, as in
``demos/experiments/timeline``:

.. literalinclude:: ../../demos/experiments/timeline/experiment.py
   :start-at: variables = {
   :end-at: }
   :dedent: 4

The same dictionary overrides the defaults of PsyNet's built-in variables,
as ``max_participant_payment`` does here; see
:class:`~psynet.experiment.Experiment` for the list. Change an experiment
variable during the experiment with ``set``:

.. code-block:: python

    CodeBlock(lambda experiment: experiment.var.set("difficulty", 2))

When code runs
--------------

Everything at the top level of ``get_timeline`` runs when a server process
imports ``experiment.py``. Each web and worker process imports it
separately, so a random draw here is not tied to a participant and may
differ between processes:

.. code-block:: python

    # Wrong: drawn at import time, not per participant
    InfoPage(f"Your number is {random.randint(0, 100)}", time_estimate=5)

Moving the draw into a page maker is also wrong, because page makers run
again when the page is refreshed. Draw in a code block and display in a page
maker, as the demo does:

.. literalinclude:: ../../demos/features/timeline/experiment.py
   :start-at: CodeBlock(
   :end-before: ModularPage(
   :dedent: 8

Branching and repetition
------------------------

Each construct takes a label. Give each one a distinct, descriptive label;
nested loops must use different labels.

:func:`~psynet.timeline.switch` takes a label, a function returning a key,
and a dictionary mapping keys to logic. Here the key is the answer to the
preceding page:

.. literalinclude:: ../../demos/features/timeline/experiment.py
   :start-at: switch(
   :end-before: while_loop(
   :dedent: 8

:func:`~psynet.timeline.while_loop` takes a label, a ``condition`` and
``logic``, plus ``expected_repetitions`` for time estimation.
:func:`~psynet.timeline.conditional` takes a label, a ``condition``, and
``logic_if_true`` and ``logic_if_false``. This loop repeats until the random
score is above 5, with feedback that depends on the score:

.. literalinclude:: ../../demos/features/timeline/experiment.py
   :start-at: while_loop(
   :end-before: ModularPage(
   :dedent: 8

:func:`~psynet.timeline.for_loop` takes keyword arguments only: ``label``,
``iterate_over``, a function returning the list for this participant, and
``logic``, a function from one item to timeline logic. It needs
``time_estimate_per_iteration`` when ``logic`` is a function, and
``expected_repetitions`` when ``iterate_over`` takes arguments such as
``participant``:

.. literalinclude:: ../../demos/features/timeline/experiment.py
   :start-at: for_loop(
   :end-at: expected_repetitions=
   :dedent: 8
   :append: ),

Organizing a long timeline
--------------------------

A :class:`~psynet.timeline.Module` groups a named section. Module names, like
trial maker IDs, must be unique within the timeline. From
``demos/experiments/timeline``:

.. literalinclude:: ../../demos/experiments/timeline/experiment.py
   :start-at: Module(
   :end-before: Module(
   :dedent: 8

:func:`~psynet.timeline.join` combines elements and lists of elements into
one sequence, so sections can be defined separately and assembled into the
full timeline:

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
- A trial maker's estimate is the trial class's ``time_estimate`` multiplied
  by the trial maker's ``expected_trials_per_participant``.
- :func:`~psynet.timeline.while_loop` multiplies the estimate of its logic by
  ``expected_repetitions``.
- :func:`~psynet.timeline.for_loop` multiplies
  ``time_estimate_per_iteration`` by ``expected_repetitions``.

.. _pre_deploy_routines:

Running code before the experiment launches
-------------------------------------------

A :class:`~psynet.timeline.PreDeployRoutine` runs a function once, on the
machine that launches the experiment, before the experiment starts. It takes
a label, the function, and a dictionary of keyword arguments for the
function. It can go anywhere in the timeline, any number of times, and shows
nothing to participants. This one configures an Amazon S3 bucket:

.. code-block:: python

    from psynet.media import setup_bucket_for_presigned_urls
    from psynet.timeline import PreDeployRoutine

    PreDeployRoutine(
        "setup_bucket_for_presigned_urls",
        setup_bucket_for_presigned_urls,
        {"bucket_name": "recordings-s3-bucket", "public_read": True},
    )

The function can also take an ``experiment`` argument. Database changes it
makes are carried into the launched experiment, so it suits database setup
tasks. Assets it deposits count as prepared before launch and are left out of
``psynet export``.

.. seealso::

   :doc:`/reference/api/timeline` in the API reference.
