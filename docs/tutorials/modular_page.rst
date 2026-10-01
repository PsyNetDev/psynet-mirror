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
the existing clip for resubmission. Completion hooks run only after successful
answer validation. Transient loss of the acceptance response triggers bounded
retries using the same recordings and original upload deadline.

Background recordings require :class:`~psynet.asset.LocalStorage`. Ordinary pages,
:class:`~psynet.page.JsPsychPage`, and browser-hosted :class:`~psynet.page.UnityPage`
resolve the permission decision before starting the task. Unity starts its loader
after that decision. Each logical page in a shared ``session_id`` gets its own
clip; the next page's capture decision completes before ``pageUpdated`` reaches
the task. Camera and screen tracks can be reused within the document. A new
document asks again through an explicit button, including after a reload.

Answer-recording controls cannot also record background video. Custom renderers
that bypass the PsyNet page lifecycle and Unity IDE debug mode cannot use this
capture API. Leaving or reloading the document can lose pending uploads; there is
no upload wait page. Fully received bytes can still be processed on the server.

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


Waiting for a recording before playback
--------------------------------------

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

The helper waits through the existing upload and processing allowance, with a
fixed 20-second polling margin. Failed or expired recordings release the wait
at the next poll. If processing stalls, the wait eventually releases without failing
the participant; the fallback must therefore handle any undeposited recording.
Legacy recordings without upload deadlines have a 20-second limit. Trial failure
and performance policies are unchanged.

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
Complete receipt starts a separate 20-second processing allowance. Retransmitting
or recovering a lost acceptance response does not extend either deadline.

Legacy experiments with ``inplace_timeline_transitions=false`` and other storage
backends retain the existing answer-upload path. This avoids routinely losing
answer recordings on every legacy page change. In an in-place experiment, crossing
a full-document boundary (for example entering Unity) can still abandon queued
bytes; avoid such a boundary before required playback. Background recording always
uses independent uploads, including on full-reload pages.

Inspecting recording outcomes
----------------------------

Open **Monitor → Recordings** for answer/background role, required policy, original
page and source, capture outcome, upload status, failure reason, and deadlines.
Only deposited recordings have download links. Early sharing loss or a duration
limit may produce a usable partial clip; its capture outcome remains visible.

The same fields are included in ``assets/manifest.csv`` during export. Unavailable
recordings remain in the manifest with no file or download URL; exporting does
not attempt to download them. Legacy recordings without the upload protocol show
``awaiting_deposit`` until their existing deposit completes. This report label is
not an S3 upload state or a new trial policy.
