.. _ModularPage:

=============
Modular Pages
=============

Modular pages are the recommended way to implement custom pages in PsyNet.
They work by splitting page design into two main components:
the `Prompts`_, constituting the information or stimulus that is presented
to the listener, and the `Controls`_, constituting the participant's
way of responding to the information or stimulus.

Prompts
-------

The following subclasses of :class:`~psynet.modular_page.Prompt` exist:

* :class:`~psynet.modular_page.AudioPrompt`

* :class:`~psynet.modular_page.ImagePrompt`

* :class:`~psynet.modular_page.ColorPrompt`

* :class:`~psynet.modular_page.VideoPrompt`

* :class:`~psynet.graphics.GraphicPrompt`



Controls
--------

A wide range of controls all of which inherit from :class:`~psynet.modular_page.Control` are available:

Audio/Video controls
~~~~~~~~~~~~~~~~~~~~

* :class:`~psynet.modular_page.AudioMeterControl`

.. image:: ../_static/images/audio_meter_control.png
  :width: 560
  :alt: AudioMeterControl

* :class:`~psynet.modular_page.AudioRecordControl`

.. image:: ../_static/images/audio_record_control_recording.png
  :width: 600
  :alt: AudioRecordControl (recording)

.. image:: ../_static/images/audio_record_control_uploading.png
  :width: 600
  :alt: AudioRecordControl (uploading)

.. image:: ../_static/images/audio_record_control_finished.png
  :width: 600
  :alt: AudioRecordControl (finished)

* :class:`~psynet.modular_page.TappingAudioMeterControl`

.. image:: ../_static/images/tapping_audio_meter_control.png
  :width: 560
  :alt: TappingAudioMeterControl


* :class:`~psynet.modular_page.AudioSliderControl`


* :class:`~psynet.modular_page.VideoRecordControl`

.. image:: ../_static/images/video_record_control_waiting.png
  :width: 600
  :alt: VideoRecordControl (waiting)

.. image:: ../_static/images/video_record_control_recording.png
  :width: 600
  :alt: VideoRecordControl (recording)

.. image:: ../_static/images/video_record_control_finished.png
  :width: 580
  :alt: VideoRecordControl (finished)


* :class:`~psynet.modular_page.VideoSliderControl`

.. image:: ../_static/images/video_slider_control.png
  :width: 580
  :alt: VideoSliderControl

* :class:`~psynet.graphics.GraphicControl`

Option controls
~~~~~~~~~~~~~~~

These classes inherit from :class:`~psynet.modular_page.OptionControl`.

* :class:`~psynet.modular_page.CheckboxControl`

.. image:: ../_static/images/checkbox_control.png
  :width: 800
  :alt: CheckboxControl

* :class:`~psynet.modular_page.DropdownControl`

.. image:: ../_static/images/dropdown_control.png
  :width: 800
  :alt: DropdownControl

* :class:`~psynet.modular_page.PushButtonControl`

.. image:: ../_static/images/push_button_control.png
  :width: 800
  :alt: PushButtonControl

* :class:`~psynet.modular_page.TimedPushButtonControl`

.. image:: ../_static/images/timed_push_button_control.png
  :width: 800
  :alt: TimedPushButtonControl

* :class:`~psynet.modular_page.RadioButtonControl`

.. image:: ../_static/images/radiobutton_control.png
  :width: 800
  :alt: RadioButtonControl


Other controls
~~~~~~~~~~~~~~

* :class:`~psynet.modular_page.NullControl`

.. image:: ../_static/images/null_control.png
  :width: 800
  :alt: NullControl

* :class:`~psynet.modular_page.NumberControl`

.. image:: ../_static/images/number_control.png
  :width: 800
  :alt: NumberControl

* :class:`~psynet.modular_page.SliderControl`

.. image:: ../_static/images/slider_control.png
  :width: 800
  :alt: SliderControl

* :class:`~psynet.modular_page.TextControl`

.. image:: ../_static/images/text_control.png
  :width: 800
  :alt: TextControl

* :class:`~psynet.modular_page.SurveyJSControl`

For the full API reference, see :doc:`/api/modular_page`.


Optional background video
-------------------------

Set ``background_recording`` on a :class:`~psynet.timeline.Page` to capture video
alongside its ordinary answer. A button page can save the choice immediately
while its camera clip uploads in the background:

.. code-block:: python

    from psynet.consent import AudiovisualConsent
    from psynet.modular_page import ModularPage, PushButtonControl, VideoRecordConfig
    from psynet.timeline import Timeline

    timeline = Timeline(
        AudiovisualConsent(time_estimate=5),
        ModularPage(
            "judgment",
            "Did the two sounds match?",
            PushButtonControl(["Yes", "No"]),
            time_estimate=10,
            background_recording=VideoRecordConfig(
                source="camera", audio=False, max_duration=120,
            ),
        ),
    )

The shorthand ``background_recording="camera"`` uses the same defaults.
``"screen"`` and ``"both"`` are also supported. Each source produces a separate
WebM asset per page visit, including when labels repeat or a
:class:`~psynet.timeline.PageMaker` generates the page.

Participants explicitly enable camera/screen access or continue without recording
before the page starts. A denied or skipped source is not requested again in the
same document. Live tracks are reused between pages; a new recorder captures
each page. Stock audiovisual consent modules must have recorded acceptance before
capture is offered. Consent pages cannot record background video.
Audio capture is off by default; screen audio availability depends on the browser
and the shared source.

By default, capture stops after 120 seconds or at 16 MiB per source. Exceeding
the size limit discards that clip; reaching the duration limit retains the
captured portion. Queue exhaustion skips capture. Missing clips expire at the
upload deadline and invalid clips fail validation, without failing the trial,
blocking analysis, or replacing its answer recording. A rejected answer keeps
the existing clip for resubmission.

This implementation supports background recordings on ordinary timeline
pages with local asset storage. It does not support
answer-recording controls, delegated pages, full-reload pages, or same-session
pages. Leaving or reloading the document can lose pending uploads; there is no
upload wait page.

Requiring a background recording
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``VideoRecordConfig(required=True)`` when a background clip is necessary for
a trial to count as valid. Set this on a page returned by the trial's
:meth:`~psynet.trial.main.Trial.show_trial`, for example:

.. code-block:: python

    def show_trial(self, experiment, participant):
        return ModularPage(
            "judgment", "Did the two sounds match?",
            PushButtonControl(["Yes", "No"]),
            time_estimate=10,
            background_recording=VideoRecordConfig(source="camera", required=True),
        )

The choice is saved immediately and independent pages can advance while the clip
uploads. The trial cannot finalize until all required clips are deposited.
Analysis of the ordinary answer can proceed; background clips never become the
trial's answer recording. Feedback that waits for trial processing and dependent
chain growth continue to respect required uploads.

Missing clips fail only their parent trial at the upload deadline, with no
recording retry. This includes denied or skipped capture. Invalid received media
can fail earlier during validation. Existing performance and payment policies
still apply. Required recording on a page without a parent trial raises an error.
With ``source="both"``, both clips are required.

Bots skip background capture and bypass the required-media condition for timeline
testing. A passing bot run does not validate recording availability; use browser
tests or manual capture to check the required policy.

Manual testing
~~~~~~~~~~~~~~

For a runnable example, use ``demos/features/background_recording``:

.. code-block:: shell

    cd demos/features/background_recording
    psynet debug local

Accept audiovisual consent, enable the camera, and answer both button pages.
Repeat after denying permission or choosing “Continue without recording”; both
answers should still advance. Continue to the optional and required comparison
trials. Hold their media requests in the browser: independent navigation should
continue, while the required trial remains unfinalized. Release its upload to
allow finalization, or leave it missing until its deadline to observe trial
failure. Inspect the recording asset's ``required_for_trial``, ``recording_role``,
``upload_status``, ``upload_failed_reason``, and ``upload_context`` fields alongside
the parent trial. Browser and server checks are described in
:doc:`/developer/running_tests`.
