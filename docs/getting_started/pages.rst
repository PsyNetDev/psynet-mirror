Pages
=====

PsyNet uses :class:`~psynet.timeline.Page` objects to represent what the participant sees
at a given point in the experiment.
These ``Page`` objects are Python objects, all inheriting from the same ``Page`` base class.
We will talk through a few examples now.

.. admonition:: Recommended starting demo
   :class: tip

   The companion demo for this chapter lives at ``demos/features/pages/``.
   It is one of the most important demos for getting comfortable with PsyNet:
   it walks through ``InfoPage``, ``ModularPage`` with push buttons, image and audio
   prompts, and audio recording with a progress display, all in a single short experiment.
   Run it with ``cd demos/features/pages && psynet debug local`` and keep
   ``experiment.py`` open as you read this chapter.

Info pages
----------

The :class:`~psynet.page.InfoPage` is the simplest type of page.
It's used to display text snippets to the participant without recording any response.
Here's an example:

.. code-block:: python

    from psynet.page import InfoPage

    InfoPage(
        """
        Welcome to the experiment!
        """,
        time_estimate=5,
    )

.. note::

    PsyNet pages are defined with ``time_estimate`` parameters.
    This parameter should correspond to how long you expect the average participant to spend
    on the page, in units of seconds, including any page loading overheads.
    These estimates are used for constructing progress bars as well as (optionally) determining
    participant payments.

Arbitrary HTML content can be specified using ``markupsafe.Markup``:

.. code-block:: python

    from markupsafe import Markup
    from psynet.page import InfoPage

    InfoPage(
        Markup(
            """
            Welcome to the <strong>experiment</strong>!
            """
        ),
        time_estimate=5,
    )

Modular pages
-------------

More complex pages can be designed using :class:`~psynet.modular_page.ModularPage` objects.
Modular pages work by combining together a *prompt*, which defines some kind of content that
is presented to the participant, and a *control*, which defines how the participant responds to that content.
PsyNet provides a library of built-in prompts and controls which in combination support
a great variety of experimental interfaces without the need to write custom HTML or JS.

For example, the following code defines a modular page that combines some text instructions
with a :class:`~psynet.modular_page.PushButtonControl` (i.e. a multiple-choice interface):

.. code-block:: python

    from psynet.modular_page import ModularPage, PushButtonControl

    ModularPage(
        label="push_button_page",
        prompt="Were those instructions clear?",
        control=PushButtonControl(
            choices=["Yes, they were clear", "Sorry, they were not clear"],
        ),
        time_estimate=5,
    )

This code demonstrates the use of an :class:`~psynet.modular_page.ImagePrompt`:

.. code-block:: python

    from psynet.modular_page import ModularPage, ImagePrompt

    ModularPage(
        label="image_prompt",
        prompt=ImagePrompt(
            "static/images/lake_mirror_reflection_yosemite.jpg",
            text="This is an example of an image prompt.",
            width="767px",
            height="512px",
            margin_bottom="25px",
        ),
        time_estimate=5,
    )

.. note::

    Here we have provided the :class:`~psynet.modular_page.ImagePrompt` constructor with a path to an image in the
    ``static`` directory. This approach is suitable for one-off pages such as experiment
    instructions. However, for large numbers of files (e.g. experiment stimuli) you would
    normally use PsyNet's asset system instead.

The following example combines an :class:`~psynet.modular_page.AudioPrompt` with a
:class:`~psynet.modular_page.TextControl`:
the participant hears the audio stimulus and then writes about it.

.. code-block:: python

    from psynet.modular_page import ModularPage, AudioPrompt, TextControl

    ModularPage(
        label="audio_prompt",
        prompt=AudioPrompt(
            "static/audio/clarinet.mp3",
            text="Listen to this audio stimulus",
        ),
        control=TextControl(),
        time_estimate=5,
    )

Here's a more complex example.
We play some audio (using an audio prompt) and then record from the participant's microphone
(using an :class:`~psynet.modular_page.AudioRecordControl`).

.. code-block:: python

    from psynet.modular_page import (
        AudioPrompt,
        AudioRecordControl,
        ModularPage,
    )
    from psynet.timeline import Event, ProgressDisplay, ProgressStage

    ModularPage(
        label="audio_prompt_and_record",
        prompt=AudioPrompt(
            "static/audio/clarinet.mp3",
            text="Listen to the recording and then try and imitate it vocally.",
            play_window=[0, 3.0],
        ),
        control=AudioRecordControl(
            duration=3.0,
            bot_response_media="static/audio/clarinet.mp3",
        ),
        time_estimate=10.0,
        events={
            "recordStart": Event(is_triggered_by="promptEnd", delay=0.5),
        },
        progress_display=ProgressDisplay(
            stages=[
                ProgressStage([0.0, 3.0], "Listen...", "blue"),
                ProgressStage([3.0, 3.5], "Get ready...", "orange"),
                ProgressStage([3.5, 6.5], "Recording...", "red"),
                ProgressStage(
                    [6.5, 7.0], "Finished recording.", "blue", persistent=True
                ),
            ],
        ),
    )

There are a few key features to point out in this example:

- We've used ``play_window`` to enforce the duration of the audio prompt to be exactly 3.0 seconds.
- By default, the audio record control would start recording at the same time that the audio prompt
  starts. However, we've used the page's ``events`` parameter to specify that we instead want the
  ``recordStart`` event to be triggered 0.5 seconds after the ``promptEnd`` event.
  See :doc:`/tutorials/event_management` for more information on event management.
- We've used the page's ``progress_display`` parameter to design a progress display that includes
  both a progress bar and some progress text. This is helpful for showing the participant what to do
  when.

.. note::

    PsyNet progress bars are defined by providing a list of progress stages.
    A progress stage is defined by a start time, an end time, a caption, and a color.
    For example, the following code defines a progress stage lasting from
    3.0 to 3.5 seconds, displayed in orange, with the caption "Get ready...":

    .. code-block:: python

        ProgressStage([3.0, 3.5], "Get ready...", "orange")

    Named colours such as ``red``, ``green``, ``blue``, ``orange``, and
    ``grey`` are mapped to the participant theme so they follow the palette
    and dark mode instead of the browser's primary red, green, and blue.
    Pass a hex value or a ``var(...)`` expression to use a colour as-is;
    see :doc:`/tutorials/theming`.


.. warning::

    The timing of PsyNet web audio events is a little imprecise;
    you should try to make your implementation robust to these imprecisions.
    For example, in the example above we leave a silent buffer of 0.5 seconds between the
    prompt finishing and the recording starting to avoid bleed-over between the two.

Available prompts and controls
------------------------------

PsyNet ships with a variety of prompts and controls. The following list highlights some of the most
common ones; for the full API, see :doc:`/api/modular_page`.

Prompts
^^^^^^^

- :class:`~psynet.modular_page.AudioPrompt` - Plays an audio file.
- :class:`~psynet.modular_page.VideoPrompt` - Plays a video.
- :class:`~psynet.modular_page.ImagePrompt` - Displays an image.
- :class:`~psynet.modular_page.ColorPrompt` - Displays a color.
- :class:`~psynet.js_synth.JSSynth` - Plays audio using a simple polyphonic synthesizer.
- :class:`~psynet.graphics.GraphicPrompt` - Displays programmatically generated animations.
- :class:`~psynet.modular_page.MusicNotationPrompt` - Displays a snippet of Western music notation.

Controls
^^^^^^^^

Option-based:

- :class:`~psynet.modular_page.PushButtonControl` - Multiple choices with buttons.
- :class:`~psynet.modular_page.KeyboardPushButtonControl` - Push buttons triggered with the keyboard.
- :class:`~psynet.modular_page.TimedPushButtonControl` - Push buttons whose timing is recorded.
- :class:`~psynet.modular_page.CheckboxControl` - Multiple choices with checkboxes.
- :class:`~psynet.modular_page.RadioButtonControl` - Multiple choices with radio buttons.
- :class:`~psynet.modular_page.DropdownControl` - Multiple choices with a dropdown menu.

Sliders and ratings:

- :class:`~psynet.modular_page.SliderControl` - Respond with a draggable slider.
- :class:`~psynet.modular_page.AudioSliderControl` - A slider linked to audio playback.
- :class:`~psynet.modular_page.VideoSliderControl` - A slider linked to video playback.
- :class:`~psynet.modular_page.RatingControl` - Respond with a rating scale.
- :class:`~psynet.modular_page.MultiRatingControl` - Respond with multiple rating scales.

Recording:

- :class:`~psynet.modular_page.AudioRecordControl` - Record audio.
- :class:`~psynet.modular_page.VideoRecordControl` - Record a video.
- :class:`~psynet.modular_page.AudioMeterControl` - Display the participant's microphone level.

Other:

- :class:`~psynet.modular_page.NumberControl` - Respond with a number.
- :class:`~psynet.modular_page.TextControl` - Respond with free-form text.
- :class:`~psynet.modular_page.SurveyJSControl` - Multi-item surveys via SurveyJS.
- :class:`~psynet.graphics.GraphicControl` - Programmatically generated animations the participant
  can interact with by clicking.

For the full API reference and screenshots, see :doc:`/tutorials/modular_page` and
:doc:`/api/modular_page`.

Exercises
---------

1. Run the companion demo at ``demos/features/pages/`` with ``psynet debug local``.
   Step through each page in turn and relate the code in ``experiment.py`` to what you see
   in the browser.
2. Go through the same demo once more, but this time find the source code for the prompts/controls
   being called (you can do this in VSCode/Cursor/PyCharm by selecting e.g.
   :class:`~psynet.modular_page.AudioPrompt` and pressing F12). The source code will contain a
   variety of additional parameters; verify that you can change them and see the results when
   refreshing the browser.

.. hint::

    Most cosmetic changes will display when you refresh the page, but if you add files to the
    ``static`` directory, you will need to stop the debug session (Ctrl+C) and rerun
    ``psynet debug local``.

.. hint::

    To skip pages in the experiment, comment them out
    (select them in your IDE, then press Edit/Toggle line comment, or the corresponding keyboard
    shortcut).

3. Try creating a new modular page that combines a prompt and a control from the list above.
   Add it to ``demos/features/pages/experiment.py`` and verify that it shows up in the
   timeline.

Further reading
---------------

Consent pages
^^^^^^^^^^^^^

Most academic institutions require experiments to obtain informed consent from the participant.
This typically involves explaining the study to the participants and confirming that they are willing
to take part. PsyNet provides several built-in consent classes, including
:class:`~psynet.consent.MainConsent`, :class:`~psynet.consent.DatabaseConsent`,
:class:`~psynet.consent.AudiovisualConsent`, and :class:`~psynet.consent.OpenScienceConsent`.

To define your own consent page, we recommend writing something like this:

.. code-block:: python

    from psynet.consent import Consent
    from psynet.page import InfoPage

    class CustomConsent(InfoPage, Consent):
        consent_text = """
        In this experiment you will be asked to ...

        This experiment involves no risk beyond...

        If you successfully complete the experiment, you will....
        """

        time_estimate = 60

        def __init__(self):
            return super().__init__(self.consent_text, time_estimate=self.time_estimate)

.. note::

    When you deploy an experiment, PsyNet checks your timeline to see if you've included a consent,
    and will throw an error if you haven't.


End pages
^^^^^^^^^

End pages are used to signify the end of the experiment. There are two main types:
:class:`~psynet.page.SuccessfulEndPage` and :class:`~psynet.page.UnsuccessfulEndPage`.
Successful end pages do not normally need to be inserted explicitly; any participant who reaches
the end of the timeline will be considered a successful completion.
Unsuccessful end pages are more useful:
we can use them to declare that a given participant has failed the experiment and needs to exit
early. For example:

.. code-block:: python

    from psynet.modular_page import ModularPage, PushButtonControl
    from psynet.page import UnsuccessfulEndPage
    from psynet.timeline import conditional, join

    join(
        ModularPage(
            "attention",
            "Are you paying attention?",
            PushButtonControl(choices=["Yes", "No"]),
            time_estimate=5,
            save_answer="attention",
        ),
        conditional(
            "attention",
            condition=lambda participant: participant.var.attention == "No",
            logic_if_true=UnsuccessfulEndPage(failure_tags=["attention"]),
        ),
    )

Custom classes
^^^^^^^^^^^^^^

It is also possible to define your own modular page classes for full control
over the experiment interface. Create a markup-only Jinja macro in
``templates/``, then a matching Python ``Control`` or ``Prompt`` subclass that
supplies CSS and JavaScript through hooks such as ``get_css()`` /
``get_css_links()`` and ``get_js_page_modules()`` rather than embedding
``<style>`` or ``<script>`` in the template.

A complete walkthrough (including the ``ColorTextAreaControl`` example and
``activate(context)`` response handling) is in
:doc:`/tutorials/writing_custom_frontends`.

**Exercise**: think of an interesting prompt or control that is not listed above.
Implement it yourself using a custom template, and add it to ``demos/features/pages/``.

Event management
^^^^^^^^^^^^^^^^

PsyNet has a special event management system that is used to manage modular components with a
temporal aspect (e.g. audio or video recorders). Most users don't need to worry about it, but it
might be useful if you get heavily into the customization side of PsyNet.
To learn more, read :doc:`/tutorials/event_management`.
