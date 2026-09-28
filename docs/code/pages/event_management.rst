Event management
================

Events schedule what happens within a page, such as when a stimulus starts
playing or when the participant may respond. Each page has a set of named
events. An event is triggered by other events, optionally after a delay, or
directly from JavaScript. Because triggers are events rather than fixed
times, the schedule adapts to delays such as media downloads or the
participant's response time.

Delaying or gating responses
----------------------------

The page's ``events`` argument replaces the definition of an event. By
default, ``responseEnable`` and ``submitEnable`` are triggered as soon as the
trial starts. To let the participant respond only after three seconds, give
``responseEnable`` a delay:

.. code-block:: python

    ModularPage(
        ...,
        events={
            "responseEnable": Event(is_triggered_by="trialStart", delay=3.0, once=True),
        },
    )

To prevent submitting before a sound or video has finished, trigger
``submitEnable`` from ``promptEnd``:

.. code-block:: python

    events={"submitEnable": Event(is_triggered_by="promptEnd")}

Adding an event
---------------

A new event is added in the same way, under a name of your choice. This page
from ``demos/features/video`` plays a soundtrack when a muted video starts
(the demo builds it inside a ``PageMaker``, omitted here):

.. literalinclude:: ../../../demos/features/video/experiment.py
   :start-at: "video_plus_audio",
   :end-at: },
   :dedent: 8
   :prepend: ModularPage(
   :append: )

:class:`~psynet.timeline.Event` takes these arguments:

``is_triggered_by``
    The name of the triggering event, a :class:`~psynet.timeline.Trigger`
    (which adds a per-trigger delay), or a list of these. ``None`` means that
    the event is only triggered from JavaScript.
``trigger_condition``
    With ``"all"`` (the default), the event is triggered once all of its
    triggers have occurred. With ``"any"``, any one trigger is enough.
``delay``
    Seconds between the trigger condition being met and the event (default
    ``0.0``).
``once``
    If ``True``, the event is triggered only the first time its trigger
    condition is met. If ``False`` (the default), it is triggered again each
    time a trigger recurs.
``message`` and ``message_color``
    Optional text to show in the progress area when the event occurs, and its
    color (default ``"black"``). Named colors such as ``red`` follow the
    :doc:`theme <theming>`.
``js``
    Optional JavaScript to run when the event occurs.

Triggering an event from JavaScript
-----------------------------------

``psynet.trial.registerEvent`` triggers an event from page JavaScript. It
accepts an optional ``info`` object, which is saved with the event in the
response's ``metadata["event_log"]``. This page module triggers a
``choiceClicked`` event when any button on the page is clicked:

.. code-block:: javascript

    export function activate({root, psynet}) {
        for (const button of root.querySelectorAll("button.choice")) {
            psynet.addPageEventListener(button, "click", () => {
                psynet.trial.registerEvent("choiceClicked", {
                    info: {buttonId: button.id},
                });
            });
        }
    }

The ``js`` argument of an event can read ``info``. Define the event with
``is_triggered_by=None``, because JavaScript triggers it:

.. code-block:: python

    events={
        "choiceClicked": Event(
            is_triggered_by=None,
            js="console.log('Clicked ' + info.buttonId);",
        ),
    }

Built-in controls trigger their own events in the same way.
:class:`~psynet.modular_page.PushButtonControl`, for example, triggers
``pushButtonClicked`` with the button's ID as ``info.buttonId``.

Running JavaScript on an event
------------------------------

Besides the ``js`` argument, page JavaScript can register handlers with
``psynet.trial.onEvent``. PsyNet's image prompt shows and hides its image
this way:

.. literalinclude:: ../../../psynet/templates/macros/prompt.html
   :language: javascript
   :start-at: psynet.trial.onEvent("promptStart", () => promptImage.style.opacity = 1);
   :end-at: psynet.trial.onEvent("promptEnd", () => promptImage.style.opacity = 0);
   :dedent: 8

Handlers run in the order they were registered. Pass a ``priority`` to change
this; higher values run first:

.. code-block:: javascript

    psynet.trial.onEvent(
        "recordEnd",
        () => psynet.log.info("Recording ended"),
        {priority: 1000},
    );

If a handler is an ``async`` function, PsyNet waits for it to finish before
running the next handler and triggering later events. The audio recorder uses
this to stop recording and stage the recording before it is uploaded:

.. literalinclude:: ../../../psynet/templates/macros/control.html
   :language: javascript
   :start-at: psynet.trial.onEvent("recordEnd", async function() {
   :end-at: });
   :dedent: 8

Events in custom components
---------------------------

A custom prompt or control changes the page's events by overriding
``update_events``, which receives the page's events and modifies them in
place. ``Event.add_trigger`` adds a trigger without
removing existing ones, so the prompt and the control can both contribute
triggers to the same event. :class:`~psynet.modular_page.AudioPrompt` makes
``trialFinish`` wait for the end of the audio:

.. literalinclude:: ../../../psynet/modular_page.py
   :pyobject: AudioPrompt.update_events
   :dedent: 4

Built-in events
---------------

Every page defines these events:

=======================  ==============================
Event                    Description
=======================  ==============================
``trialConstruct``       First-time setup for the page, such as loading
                         media. It happens once per page, even if the trial
                         restarts.
``pageReady``            The page has been activated and may navigate.
``trialManualRequest``   The participant clicked Start, on pages created
                         with ``start_trial_automatically=False``.
``trialPrepare``         Preparation of the trial. It reruns each time the
                         trial restarts.
``trialStart``           The trial starts.
``responseEnable``       The participant may start responding.
``submitEnable``         The participant may submit, for example by
                         clicking Next.
``trialFinish``          The trial has come to its natural end, which cues
                         clean-up.
``trialFinished``        Clean-up after ``trialFinish`` is complete.
``trialStop``            The trial was stopped early, which cues clean-up.
``trialStopped``         Clean-up after ``trialStop`` is complete.
=======================  ==============================

``trialFinish`` is only triggered on pages whose prompt or control has a
natural end: audio, video and :class:`~psynet.js_synth.JSSynth` prompts end on
``promptEnd``, and recording controls end on ``recordEnd``.

Prompts and controls add further events:

================================  ===================================  ======================================
Event                             Defined in                           Description
================================  ===================================  ======================================
``promptStart``                   ``AudioPrompt``, ``VideoPrompt``,    The prompt starts playing or is shown.
                                  ``ImagePrompt``, ``JSSynth``,
                                  ``MusicNotationPrompt``
``promptEnd``                     ``AudioPrompt``, ``VideoPrompt``,    The prompt stops playing or is hidden.
                                  ``JSSynth``, ``ImagePrompt``
                                  (with ``hide_after``)
``pushButtonClicked``             ``PushButtonControl`` and its        A button is clicked.
                                  subclasses
``sliderChange``                  ``SliderControl`` and its            The slider moves.
                                  subclasses
``sliderMinimalInteractions``     ``SliderControl`` and its            The participant has moved the slider
                                  subclasses                           the minimum number of times.
``sliderMinimalTime``             ``SliderControl`` and its            The minimum time on the slider has
                                  subclasses, ``FrameSliderControl``   passed.
``recordStart``                   ``AudioRecordControl``,              Recording starts.
                                  ``VideoRecordControl``
``recordEnd``                     ``AudioRecordControl``,              Recording ends.
                                  ``VideoRecordControl``
``autoSubmit``                    ``AudioRecordControl``,              The page submits itself, when the
                                  ``VideoRecordControl``               control has ``auto_advance=True``.
``audioMeterMinimalTime``         ``AudioMeterControl``                The minimum time on the meter has
                                                                       passed.
``showNextButton``                ``SurveyJSControl`` and its          PsyNet's Next button is shown.
                                  subclasses
``graphicPromptEnableResponse``   ``GraphicPrompt``                    A frame with
                                                                       ``activate_control_response=True`` is
                                                                       reached.
``graphicPromptEnableSubmit``     ``GraphicPrompt``                    A frame with
                                                                       ``activate_control_submit=True`` is
                                                                       reached.
================================  ===================================  ======================================

The browser console logs each event as it occurs:

.. figure:: ../../_static/images/experimenter/event_management/console_log.png
  :width: 600
  :align: center
