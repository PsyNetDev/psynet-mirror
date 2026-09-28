.. |br| raw:: html

   <br />

Event management
================

Use PsyNet's event management system to schedule what happens within a page, for example when a stimulus starts playing or when the participant may respond. You do not need to understand the whole system to customize the timing of your own pages.

The event management system is modeled on the idea that a given page will present a *trial* to the participant, where a trial comprises a sequence of events in some kind of temporal order. Importantly, the precise timing of these events may depend on certain unpredictable variables, for example the time it takes for the participant to give a response, or the time it takes to download a certain media file, etcetera.

The event management system predefines a certain number of events, listed in the table below:

==================  ==============================
Event name          Description
==================  ==============================
``trialConstruct``  Initiates first-time setup for the page (e.g., downloading media assets).

                    This only happens once on a given page, even if the trial is restarted.
``trialPrepare``    Initiates preparation of the trial. This will be rerun each time the trial is restarted.
``trialStart``      Initiates the trial itself.
``responseEnable``  Allows the user to start entering their response.
``submitEnable``    Allows the user to submit their response, e.g. by clicking ‘Next’.
``trialFinish``     Signals the natural end of a trial, and cues clean-up routines.
``trialFinished``   Signals the completion of clean-up routines after the natural end of a trial.
``trialStop``       Signals an early stopping of the trial, and cues clean-up routines.
``trialStopped``    Signals the completion of clean-up routines after the early stopping of a trial.
==================  ==============================

The final four events (``trialFinish``, ``trialFinished``, ``trialStop``, and ``trialStopped``) only apply to trials with a finite length, which by default currently only applies for trials with audio or video recording.

Particular modular page components then may define additional events. For example:

=============================   ==========================  ===================================
Event named                     Defined in                  Description
=============================   ==========================  ===================================
``promptStart``                 ``AudioPrompt``,            Initiates the display/playback

                                ``ImagePrompt``,            of the prompt

                                ``VideoPrompt``
``promptEnd``                   ``AudioPrompt``,            Ends the display/playback

                                ``ImagePrompt``,            of the prompt

                                ``VideoPrompt``
``pushButtonClicked``           ``PushButtonControl``,      Triggered when a button is clicked

                                ``TimedPushButtonControl``
``uploadStart``                 ``AudioRecordControl``,     Initiates the upload of the recording

                                ``VideoRecordControl``
``uploadEnd``                   ``AudioRecordControl``,     Triggered when the upload completes

                                ``VideoRecordControl``      successfully
``uploadFail``                  ``AudioRecordControl``,     Triggered when the upload fails

                                ``VideoRecordControl``
``sliderChange``                ``SliderControl``,          Triggered when the slider moves

                                ``AudioSliderControl``
``sliderMinimalInteractions``   ``SliderControl``,          Triggered once the participant has

                                ``AudioSliderControl``      surpassed the minimal interactions

                                                            threshold for the slider
=============================   ==========================  ===================================

On a given PsyNet page, you can see the events listed in the console log as and when they are generated:

.. figure:: ../../_static/images/experimenter/event_management/console_log.png
  :width: 600
  :align: center

There are two main ways in which a PsyNet user might manipulate this event management system: (a) defining new event listeners for a given event; (b) changing the triggers for a pre-existing event; (c) defining a completely new event.

Defining a new event
--------------------

New events are defined by use of the page’s ``events`` argument. Take the following example from the audio demo:

.. code-block:: python

    from psynet.modular_page import VideoPrompt
    from psynet.timeline import Event, MediaSpec

    ModularPage(
        "video_plus_audio",
        VideoPrompt(
            "/static/birds.mp4",
            "Here we play a video, muted, alongside an audio file.",
            mirrored=True,
            muted=True,
        ),
        time_estimate=5,
        media=MediaSpec(audio={
            "soundtrack": "/static/funk-game-loop.mp3"
        }),
        events={
            "playSoundtrack": Event(
                is_triggered_by="promptStart",
                delay=0.0,
                message="Playing audio now",
                message_color="red",
                js="psynet.audio.soundtrack.play()",
            )
        },
    )

The events argument should be a dictionary, where the keys correspond to event names, and the values correspond to ``Event`` objects (where the ``Event`` class is imported from ``psynet.timeline``). When defining a new event, we are free to make up our own name; here we chose ``playSoundtrack``.

The first argument of the ``Event`` constructor is ``is_triggered_by``. This determines when the event is triggered. The simplest way of using this argument is to provide the name of another event; in that case, the event will be triggered directly by the occurrence of the named event.

It is also possible to define multiple triggers by providing a list of such events. The resolution of multiple event triggers is determined by a further argument called ``trigger_condition``. If ``trigger_condition="all"`` (default), then the new event will only be triggered once all its trigger events have occurred. If ``trigger_condition="any"``, then the new event will be triggered when *any* of its trigger events occur.

The ``once`` argument (defaulting to ``True``) determines how many times the event may be triggered. If ``once=True``, then the event will only be triggered once, even if its triggers occur multiple times. If ``once=False``, then the event will be triggered again each time one of its triggers occurs (assuming all required trigger events have occurred in the case of ``trigger_condition="any"``).

The ``message`` argument determines an optional on-screen message to present when the event occurs. This message is presented in the same space as progress bar messages (see the ``progress_display`` argument of ``Page``). The color of this message can be customized with the ``message_color`` argument, which takes arbitrary HTML color specifications, defaulting to "``black``".

Lastly, the ``js`` argument defines an optional Javascript expression to execute when the event occurs. This can be a quick way to inject Javascript code into the page without having to customize any HTML templates.

So far we assumed that we want our event to be triggered by other PsyNet events. What if we want it to be triggered directly in Javascript? We can achieve this by using the ``psynet.trial.registerEvent`` function in Javascript. For example, the following JavasScript code registers a ``pushButtonClicked`` event each time one of three buttons is pressed:

.. code-block:: html

    <button type="button" id="btn-1" onclick=btnClick>Button 1</button>
    <button type="button" id="btn-2" onclick=btnClick>Button 2</button>
    <button type="button" id="btn-3" onclick=btnClick>Button 3</button>

    <script>
        function btnClick() {
            let id = this.id;
            psynet.trial.registerEvent(
                "pushButtonClicked",
                {info: {buttonId: id}}
            );
        }
    </script>

This registers an event called "``pushButtonClicked``". When we register an event, we can provide an optional ``info`` dictionary (or in Javascript terms, an Object) of additional information. Here our dictionary has one piece of information: the ``buttonId``. This information is saved in the metadata of the response to PsyNet pages, which can be accessed in the page’s ``format_answer`` method, or in the ``Response`` table, or in ``response.csv`` as exported by PsyNet. It can also be accessed within the Javascript code defined in the event’s ``js`` argument as an object called ``info``. I could use this fact to write a "``pushButtonClicked``" handler that displays an alert on the screen every time I press a button:

.. code-block:: python

    ModularPage(
        label="demo",
        prompt="Click a button.",
        control=TimedPushButtonControl(
            choices=["A", "B", "C"],
        ),
        time_estimate=5,
        events={
            "pushButtonClicked": Event(
                is_triggered_by=None,
                js="alert('You pressed button ' + info.buttonId + '.');"
            )
        }
    )


Updating pre-defined events
---------------------------

Sometimes we want to update pre-defined events in a PsyNet page. For example, the standard PsyNet page defines the ``responseEnable`` event as follows (see ``timeline.py``):

.. code-block:: python

    "responseEnable": Event(
        is_triggered_by="trialStart",
        delay=0.0,
        once=True
    )

However, we might want to customize this, for example only allowing the participant to start responding after three seconds. We would achieve this by customizing the ``events`` argument as before, but this time providing a revised definition of the ``responseEnable`` event.

.. code-block:: python

    events={
        "responseEnable": Event(
            is_triggered_by="trialStart",
            delay=3.0,
            once=True
        )
    }

Custom prompts/controls and event management
--------------------------------------------

When implementing a custom prompt or control, the preferred way to customize event management is by overriding the ``update_events`` method. This event takes the default ``events`` dictionary from the superclass and updates it as required. For example, here is the ``update_events`` method from PsyNet’s ``AudioPrompt`` class:

.. code-block:: python

    def update_events(self, events):
        super().update_events(events)

        events["promptStart"] = Event(
            is_triggered_by=[
                Trigger(
                    triggering_event="trialStart",
                    delay=0,
                )
            ]
        )

        events["promptEnd"] = Event(is_triggered_by=[], once=False)
        events["trialFinish"].add_trigger("promptEnd")

Updating ``events`` in this way allows one to take advantage of the ``Event.add_trigger`` method. This allows you to add a trigger to a pre-existing ``Event`` without losing the pre-existing triggers. This approach is useful because it allows a given ``Event`` to compile triggers from multiple locations: in this case, for example, it lets the ``trialFinish`` event wait for triggers from both the ``Prompt`` and the ``Control``.

Defining new event listeners for a given event
----------------------------------------------

The previous section showed us one way to execute custom Javascript after a given event occurs: create a new event that is triggered by that event, and include a ``js`` argument with some custom Javascript to execute.

Such event handlers can also be defined within the prompt or control template, using the function ``psynet.trial.onEvent``. For example, the ``image`` prompt macro contains the following code:

.. code-block:: python

    psynet.trial.onEvent(
        "promptStart",
        () => promptImage.style.opacity = 1
    );


    psynet.trial.onEvent(
        "promptEnd",
        () => promptImage.style.opacity = 0
    );

This code is responsible for timing the presentation of an image. When the ``promptStart`` event occurs, the image is made opaque; when the ``promptEnd`` event occurs, the image is made transparent. In case you’re unfamiliar with the notation, () => … is simply Javascript shorthand for an anonymous function (i.e., a function that is defined without a name).

Advanced event management
-------------------------

Sometimes you want to ensure that event handlers are triggered in a specific order. By default, they will simply occur in the order that they are registered. This can be overridden by providing an optional ``priority`` argument to the ``onEvent`` call. Higher priority numbers are executed first. For example, the following code would display a ‘Recording ended!’ message as soon as the ``recordEnd`` event was triggered, and this message would come before any of the other event handlers were triggered.

.. code-block:: python

    psynet.trial.onEvent(
        "recordEnd",
        () => alert("Recording ended!"),
        {priority: 1000}
    );

Sometimes you want to ensure that the event handler finishes before moving onto the next handler, or indeed before triggering the next event in the series. This is achieved by defining the event handler as an *async function*. An async function is a relatively recent Javascript construct that corresponds to a time-consuming process that one might want to wait for. The details of async functions are outside the scope of this page, but we will give an example of an event handler that uses async functions, drawn from the video recorder macro (and slightly paraphrased):

.. code-block:: python

    psynet.trial.onEvent("recordEnd", async function() {
        await videoRecorder.stopRecording();
        psynet.media.data["videoBlob"] = await videoRecorder.getBlob();
        await videoRecorder.reset();
    });

Async functions include the special keyword ``await``. This keyword tells Javascript to wait until the statement has finished executing. Most programming languages (e.g., Python) wait by default, but Javascript doesn’t normally wait, because it wants to keep the user experience snappy. This can cause problems when we have subsequent lines of code that depend on the outcome of previous lines. In the example above, it takes a little time for the ``videoRecorder`` to stop and for us to collect the data from it. Only then do we want to proceed with the next events, which will be responsible for uploading the video. We therefore implement our event handler as an async function, so that Javascript will wait for the function to be complete before moving onto the next event.
