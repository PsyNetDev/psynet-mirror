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

Code blocks from different participants can run at the same time. For
periodic work that isn't tied to a participant, decorate a static method of
the experiment class with ``scheduled_task`` from :mod:`psynet.experiment`,
for example ``@scheduled_task("interval", seconds=10, max_instances=1)``, as
``demos/features/bot_2`` does. Scheduled tasks run in the clock process.

Remembering things about a participant
--------------------------------------

Participant variables live in ``participant.var``. Outside a lambda, assign
them directly; inside a lambda, use ``set``, because Python doesn't allow
assignments in lambdas:

.. code-block:: python

    participant.var.color = "red"
    CodeBlock(lambda participant: participant.var.set("color", "red"))

Use ``participant.var.get("score")`` when a variable may not be set yet: like
``dict.get``, it returns ``None``, or the default you pass, as in
``participant.var.get("score", default=0)``. Attribute access, as in
``participant.var.score``, raises ``KeyError`` for a variable that isn't set.

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

More precisely, PsyNet calls a page maker's function again each time the
participant moves to the next element inside it, when the function returns
several elements, and whenever the page is refreshed. Keep the function free
of side effects. When it returns :meth:`~psynet.trial.main.Trial.cue`, only
the first call creates the trial, so later calls don't change it, but they
still repeat any work the function does. If that work is expensive, do it once
in a code block, store the result in ``participant.var``, and have the page
maker only read it.

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
``logic``, plus ``expected_repetitions`` for time estimation. By default
(``fix_time_credit=True``), every participant gets time credit for
``expected_repetitions`` iterations, however many they actually do.
``max_loop_time`` limits the time in the loop in seconds; participants who
reach it while the condition still holds are sent to the unsuccessful end
unless ``fail_on_timeout=False``. ``extend_while`` is checked at the start of
each pass through the loop; whenever it returns ``True``, the
``max_loop_time`` clock restarts from zero, for example while a
participant's recording is still uploading.
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

When PsyNet ends a multiplayer session itself (a participant waited too long
at a barrier, was too slow to reach the next one, or their group became too
small), the unsuccessful end page says why, for example "We waited too long
for other participants, so we ended your session." Other endings, such as
failing a prescreen, get no such line. To explain your own reasons, pass a
function of the participant that returns a line, or ``None`` to keep
PsyNet's:

.. code-block:: python

    def failure_message(participant):
        if "performance_check" in participant.failure_tags:
            return "Your answers suggest that your headphones aren't working."
        return None

    Timeline(..., unsuccessful_end=UnsuccessfulEndLogic(failure_message=failure_message))

You can also pass a plain string, but it replaces PsyNet's own lines for
every participant, including the multiplayer ones. Returning ``""`` shows no
line at all.

To end without waiting for a click on Finish, for example in a multiplayer
game, pass ``time_limit``. The page then adds "This page continues by itself
in 3 s." and counts down:

.. code-block:: python

    Timeline(
        ...,
        successful_end=SuccessfulEndLogic(time_limit=3),
        unsuccessful_end=UnsuccessfulEndLogic(time_limit=3),
    )

The rejected-consent page has no Finish button, so
:class:`~psynet.end.RejectedConsentLogic` does not take ``time_limit``.

Time limits
-----------

Pass ``time_limit`` to any :class:`~psynet.timeline.Page` to allow only that
many seconds on it. The page shows "15 s left" at the top, where waiting
messages also appear, counting down, and when time runs out it submits
``time_limit_answer`` for the participant:

.. code-block:: python

    ModularPage(
        "offer",
        "How many coins do you offer?",
        PushButtonControl(choices=list(range(11))),
        time_limit=15,
        time_limit_answer="timeout",
        time_estimate=15,
    )

The server counts the time from when the participant reached the page, so
reloading the page does not restart the countdown. The time includes any
wait before the participant can answer, such as audio that must finish
before the Next button is enabled, so allow for it in ``time_limit``. The
server also treats an answer that arrives more than 5 seconds after the
limit as timed out, so a tampered or stalled page cannot take longer: it
records ``time_limit_answer``, or with ``CURRENT_ANSWER`` the late answer
itself, unvalidated and with ``time_limit_reached`` set. A timed page cannot have a ``session_id``. To place the countdown
yourself, put an element with the attribute ``data-psynet-seconds-left`` in
the page's content, for example
``<p>Answer within <span data-psynet-seconds-left></span> seconds.</p>``.

Answers given because of the time limit skip validation, and their
:attr:`~psynet.timeline.Response.time_limit_reached` is ``True``. A later page
maker or code block can check the previous page with
``participant.response.time_limit_reached``.

In a group experiment, a time limit covers only its page. A following
:class:`~psynet.sync.GroupBarrier` with ``late_after`` waits for a member
who has started a timed page since the group's previous barrier until the
page's time limit has run out plus 10 seconds, which is enough for an answer
sent at the deadline to arrive. This also holds once they have answered and
moved on to untimed pages, so finishing early never makes a member late. So
give decision pages a ``time_limit``, and the barrier after them
``late_after`` rather than a long ``max_wait_time``; see
:ref:`rounds-slow-players` for a worked example.

To keep what the participant has entered instead of a fixed answer, pass
:data:`~psynet.timeline.CURRENT_ANSWER`:

.. code-block:: python

    from psynet.timeline import CURRENT_ANSWER

    ModularPage(
        "story",
        "Write a short story.",
        TextControl(),
        time_limit=120,
        time_limit_answer=CURRENT_ANSWER,
        time_estimate=120,
    )

The page then submits its controls' current answer, for example a half-written
text, which is formatted as usual but not validated. If the page has no answer
to submit, ``None`` is recorded. Just before a timed page submits itself, the
browser dispatches a ``psynet:timeLimitReached`` event on ``document``, so
custom JavaScript can stage its state first:

.. code-block:: javascript

    document.addEventListener("psynet:timeLimitReached", () => {
        psynet.response.staged.rawAnswer = currentDrawing();
    });

With ``CURRENT_ANSWER``, a page with a built-in control submits that
control's answer; other pages submit ``psynet.response.staged``.

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
