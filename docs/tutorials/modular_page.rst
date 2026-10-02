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

Capture requires accepted audiovisual consent and an explicit browser permission
step before the task starts. Participants can continue without recording; optional
pages do not request skipped or denied sources again. Later required pages offer
another permission decision when their source is unavailable. Audio is
off by default. Screen audio availability depends on the browser and shared source.

By default, capture stops after 120 seconds or at 16 MiB per source. Exceeding
the size limit discards that clip; reaching the duration limit retains the
captured portion. Missing optional clips do not fail the trial or block analysis.
See :class:`~psynet.modular_page.VideoRecordConfig` for configuration options.

Background recordings require :class:`~psynet.asset.LocalStorage` and in-place
timeline transitions. These settings are checked at startup for static pages and
when generated pages are rendered. Background recording supports
ordinary pages, :class:`~psynet.page.JsPsychPage`, and browser-hosted
:class:`~psynet.page.UnityPage`. Pages sharing a ``session_id`` each get their own clip.

Consent pages and answer-recording controls cannot also record background video.
Unity IDE debug mode and custom renderers that bypass the PsyNet page lifecycle
are unsupported. Manually leaving or reloading the document warns about pending
uploads, which are lost if the participant chooses to leave.

Requiring a background recording
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

The answer is saved immediately and its analysis can proceed, but the trial cannot
finalize until all required clips are deposited. Independent pages can advance.

Missing clips fail only their parent trial at the upload deadline, with no
recording retry. This includes denied or skipped capture. Existing performance
and payment policies still apply. Required recording on a page without a parent
trial raises an error.
With ``source="both"``, both clips are required.

Required background pages run ``on_complete`` after successful validation and
asset reservation, so completion hooks see the pending requirement. Optional
pages retain ordinary answer-saving and completion-hook behavior.

Bots skip background capture and bypass the required-media condition for timeline
testing. A passing bot run does not validate recording availability; use browser
tests or manual capture to check the required policy.

Try the demo
~~~~~~~~~~~~

For a runnable example, use ``demos/features/background_recording``:

.. code-block:: shell

    cd demos/features/background_recording
    psynet debug local

Compare optional and required trials with camera permission enabled and denied.
Answers should advance in both cases; a missing required clip fails its trial at
the deadline. Inspect the results under **Monitor → Recordings**.


Waiting for a recording before playback
---------------------------------------

For playback outside a trial, use :func:`~psynet.page.wait_for_recording` and
check whether the recording was deposited before constructing the playback page.
This preserves navigation when media is unavailable. For example, after a
recording page with label ``recording``::

    from psynet.modular_page import ModularPage, VideoPrompt
    from psynet.page import InfoPage, wait_for_recording
    from psynet.timeline import PageMaker, join

    playback = join(
        wait_for_recording(lambda participant: participant.assets["recording"]),
        PageMaker(
            lambda participant: ModularPage(
                "playback",
                VideoPrompt(participant.assets["recording"], "Your recording."),
                time_estimate=5,
            )
            if participant.assets["recording"].deposited
            else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
            time_estimate=5,
        ),
    )

The helper stops waiting when the recording is available, fails, or reaches its
waiting limit. Always provide a fallback for an undeposited recording. Legacy
recordings without upload deadlines have a 20-second waiting limit.

Video answer upload defaults
----------------------------

:class:`~psynet.modular_page.VideoRecordControl` submits answers independently of
video uploads when using :class:`~psynet.asset.LocalStorage` and in-place timeline
transitions (the default). Trial-dependent analysis and finalization wait for
deposit. A missing upload fails only its trial at the upload deadline, without a
recording retry; configured performance rules still apply. Non-trial playback
should use the fallback pattern above.

Custom :meth:`~psynet.timeline.Page.validate` implementations receive recording
metadata with ``None`` ID/URL placeholders before acceptance. Final asset IDs and
URLs are installed before the answer is saved and ``on_complete`` runs, but the
bytes may still be uploading. Analyze recording bytes through the trial's
post-trial processing after deposit; do not fetch them inside answer validation
or ``on_complete``.

The upload deadline starts when the answer is accepted. The allowance is
30 seconds plus twice the transfer time at 1 Mbit/s, bounded to 60–600 seconds.
Complete receipt starts a separate 20-second processing allowance. Retries do not
extend either deadline.

With ``inplace_timeline_transitions=false`` or other storage backends, answer video
uploads still complete before navigation. Background recording is unsupported
with these settings. In-place experiments drain pending uploads before full-page
transitions and recruiter exit; failures and the original deadlines bound this wait.

Shared camera and screen tracks stay active across pages until the document closes.
Clips with audio disabled exclude microphone tracks, even when the shared camera
was previously used with audio. In the asynchronous path, denied capture saves the
answer and fails its parent trial at the upload deadline instead of throwing a
permission error. Legacy upload behavior is unchanged.

Uploads must begin with the WebM/EBML header. This rejects obvious non-media input;
it does not decode the file or guarantee that the recording is playable.

The first answer screen recording displays a **Share screen** button before task
startup. Compatible later pages reuse the stream; a full reload requires a new
permission decision. Skipping capture follows the missing-upload policy above.

Inspecting recording outcomes
-----------------------------

Open **Monitor → Recordings** for each clip's source, required/optional policy,
capture outcome, upload status, and failure reason. These fields also appear in
``assets/manifest.csv``. Unavailable recordings remain listed without download
links; partial clips are identified by their capture outcome.
