Recording video and handling uploads
====================================

Record answer or background video while allowing independent pages to advance.
Use the waiting and fallback pattern below when a later page needs the recording.

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
If the experiment uses PsyNet's audiovisual consent module, a page with background
recording placed before it is rejected when the experiment starts.

By default, capture stops after 120 seconds or at 16 MiB per source. Reaching
either limit keeps the part captured so far. Missing optional clips never fail
the trial, block analysis, or hold any page.
See :class:`~psynet.modular_page.VideoRecordConfig` for configuration options.

Background recordings require :class:`~psynet.asset.LocalStorage` and in-place
timeline transitions. These settings are checked at startup for static pages and
when generated pages are rendered. Background recording supports
ordinary pages, :class:`~psynet.page.JsPsychPage`, and browser-hosted
:class:`~psynet.page.UnityPage`. Pages sharing a ``session_id`` each get their own clip.
If an answer is rejected, recording continues, so the clip submitted with the
corrected answer also covers the time before the rejection.
An answer rejected within the first second of recording keeps only what is
recorded after the rejection.

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

Because feedback waits for the trial to be finalized (so that its score is set),
a pending required clip also holds the feedback page until the clip is deposited
or fails. This wait is bounded by the clip's upload deadline plus the 5-minute
storage bound; in practice clips usually arrive within seconds. Optional clips
never hold feedback.

A missing clip fails only its parent trial, with no recording retry; existing
performance and payment policies still apply. If capture was denied, skipped,
or otherwise unavailable when the answer was submitted, the trial fails
immediately; otherwise it fails if the clip has not arrived by its upload
deadline. Required recording on a page without a parent trial raises an error.
With ``source="both"``, both clips are required.

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
Answers should advance in both cases; a missing required clip fails its trial. Inspect the results under **Monitor → Recordings**.


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
deposit. Non-trial playback should use the fallback pattern above.

A missing recording fails only its trial, never the participant, and is never
recaptured; configured performance rules still apply.

- If the browser already knows a recording is unavailable when the answer is
  submitted (for example, camera access was denied, or the recording was too
  large), the trial fails immediately.
- Otherwise the trial fails if the recording has not arrived by its upload
  deadline.

Custom :meth:`~psynet.timeline.Page.validate` implementations receive recording
metadata with ``None`` ID/URL placeholders before acceptance. Final asset IDs and
URLs are installed before the answer is saved and ``on_complete`` runs, but the
bytes may still be uploading. Analyze recording bytes through the trial's
post-trial processing after deposit; do not fetch them inside answer validation
or ``on_complete``.

Deadlines and retries
---------------------

The upload deadline starts when the answer is accepted. The allowance is
30 seconds plus twice the transfer time at 1 Mbit/s, bounded to 60–600 seconds.
The browser retries a failed upload with increasing delays until that deadline.

Once received, a recording must be stored within 5 minutes. This includes any
time spent waiting for a free worker; the storage step itself may run for up to
2 minutes. Retries never extend either deadline. Waits that depend on a
recording, such as feedback and :func:`~psynet.page.wait_for_recording`, last
until these deadlines have passed.

If the reply to a recording submission is lost, the participant is asked to check
their connection and press **Next** again. The same submission is sent again, so
the server can return its original acceptance; the answer is not recorded twice.

In-place experiments wait for pending uploads before full-page transitions and
recruiter exit, displaying an upload message; failures and the original deadlines
bound this wait. Deliberate early-exit and error redirects can abandon pending
uploads without an additional browser warning.

Bots upload their ``bot_response_media`` files through the same upload route
after their answer is accepted, so automated runs and load tests exercise the
same path as participants.

Camera and screen access
------------------------

Consecutive recording pages reuse the camera and screen streams without asking
again. Once a page that does not record is shown, including a waiting page or a
page in the same ``session_id``, recording stops and PsyNet releases the streams,
so the camera light and screen-sharing banner turn off. A later recording page turns the
camera back on without asking again when access was already granted; screen
sharing is always requested anew. Clips with audio disabled stop and remove cached audio
tracks, even when the camera was previously used with audio.

The first answer screen recording displays a **Share screen** button before task
startup. A full page reload requires a new permission decision. Skipping capture
follows the missing-recording policy above.

Uploads must begin with the WebM/EBML header. This rejects obvious non-media input;
it does not decode the file or guarantee that the recording is playable.

Legacy upload path
------------------

With ``inplace_timeline_transitions=false`` or storage other than
:class:`~psynet.asset.LocalStorage`, answer videos still upload together with the
answer. Both paths now share the same capture code, which changes the legacy path
in a few ways:

- Recordings are WebM only; there is no fallback to other browser formats.
- If capture fails, the participant is told that the recording could not be
  captured and asked to allow access and reload the page. Until they reload, the
  page cannot be submitted; reloading shows the recording page again, so they
  can record again. The server also rejects an empty recording instead of
  storing it as a valid one.
- If the browser does not confirm that recording stopped within 3 seconds, the
  part captured so far is kept.

Background recording is not available on the legacy path.

Inspecting recording outcomes
-----------------------------

Open **Monitor → Recordings** for each clip's source, required/optional policy,
capture outcome, upload status, and failure reason. These fields also appear in
``assets/manifest.csv``. Unavailable recordings remain listed without download
links; clips that stopped early (for example at the size or duration limit) are
identified by their capture outcome.
