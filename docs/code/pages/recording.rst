Recording video and audio, and handling uploads
===============================================

Answer recordings from :class:`~psynet.modular_page.VideoRecordControl` and
:class:`~psynet.modular_page.AudioRecordControl` upload independently of page
navigation. Wait for deposit and
provide a fallback when a later page needs the recording.

Waiting for a recording before playback
---------------------------------------

For playback on any later page, including a later page of the same trial,
use :func:`~psynet.page.wait_for_recording` and check whether the recording
was deposited before constructing the playback page. Only trial analysis and
feedback wait for the recording automatically.
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
recordings, which upload with the answer, have a 20-second waiting limit.

Answer upload defaults
----------------------

:class:`~psynet.modular_page.VideoRecordControl` and
:class:`~psynet.modular_page.AudioRecordControl` submit answers independently of
their recordings' uploads when using :class:`~psynet.asset.LocalStorage` and in-place timeline
transitions (the default). Trial-dependent analysis and finalization wait for
deposit. Non-trial playback should use the fallback pattern above.

A missing recording fails only its trial, never the participant, and is never
recaptured; configured performance rules still apply.

- If the browser already knows a recording is unavailable when the answer is
  submitted (for example, camera access was denied, or the recording was too
  large), the trial fails immediately.
- Otherwise the trial fails if the participant's browser stops uploading the
  recording, for example because it was closed (see below).

Custom :meth:`~psynet.timeline.Page.validate` implementations receive recording
metadata with ``None`` ID/URL placeholders before acceptance. Final asset IDs and
URLs are installed before the answer is saved and ``on_complete`` runs, but the
bytes may still be uploading. Analyze recording bytes through the trial's
post-trial processing after deposit; do not fetch them inside answer validation
or ``on_complete``.

Slow connections, expiry and retries
------------------------------------

A slow upload is not failed for being slow. While the participant's browser
still holds a recording, it renews the upload every 30 seconds, and the server
renews it while bytes keep arriving. An upload connection that receives less
than 64 KB in 2 minutes is closed and retried. The recording is treated as missing only
if 2 minutes pass without either, for example because the browser was closed
or lost its connection, or if it is still not uploaded 30 minutes after the
answer was accepted. The browser retries a failed upload with increasing delays
until the server reports it expired, or gives up after five internal server
errors in a row, so a server fault cannot keep the participant waiting.

To keep a slow connection from building up a backlog, a participant can be at
most one recording page ahead of their uploads. When they submit a recording
page while uploads from two earlier recording pages are still pending, they see
an upload message until the older ones finish, as they would have waited for an
upload inside the submission before. Participants with fast connections never
wait.

The browser keeps pending recordings in memory and holds at most 32 recordings,
or 256 MiB (two maximum-size video recordings), at once. A page
whose recordings would not fit also waits until earlier uploads finish.

Once received, a recording must be stored within 5 minutes. This includes any
time spent waiting for a free worker; the storage step itself may run for up to
2 minutes. Waits that depend on a recording, such as feedback and
:func:`~psynet.page.wait_for_recording`, end as soon as the recording is stored
or has failed.

If the reply to a recording submission is lost, the participant is asked to check
their connection and press **Next** again. The same submission is sent again, so
the server can return its original acceptance; the answer is not recorded twice.

In-place experiments wait for pending uploads before full-page transitions and
recruiter exit, displaying an upload message until each upload has been
received or has failed. Deliberate early exit, Lucid termination and error redirects
can abandon pending uploads without an additional browser warning.

Bots upload their ``bot_response_media`` files through the same upload route
after their answer is accepted, so automated runs and load tests exercise the
same path as participants.

Camera and screen access
------------------------

Consecutive recording pages reuse the camera and screen streams without asking
again. Once a page that does not record is shown, PsyNet releases them, so the
camera light and screen-sharing banner turn off. A later recording page turns the
camera back on without asking again when access was already granted; screen
sharing is always requested anew. Clips with audio disabled stop and remove cached audio
tracks, even when the camera was previously used with audio.

The first answer screen recording displays a **Share screen** button before task
startup. A full page reload requires a new permission decision. Skipping capture
follows the missing-recording policy above.

Video uploads must begin with a WebM/EBML header and audio uploads with a
RIFF/WAVE header; the server decides which format each recording must have. This
rejects obvious non-media input; it does not decode the file or guarantee that
the recording is playable. Audio recordings are uncompressed WAV, so their size
limit is derived from the control's ``duration`` and number of channels.

Legacy upload path
------------------

With ``inplace_timeline_transitions=false`` or storage other than
:class:`~psynet.asset.LocalStorage`, answer recordings still upload together with
the answer. Audio capture is unchanged on this path. For video, both paths now
share the same capture code, which changes the legacy path in a few ways:

- Recordings are WebM only; there is no fallback to other browser formats.
- If capture fails, the participant is told that the recording could not be
  captured and asked to allow access and reload the page. Until they reload, the
  page cannot be submitted; reloading shows the recording page again, so they
  can record again. The server also rejects an empty recording instead of
  storing it as a valid one.
- If the browser does not confirm that recording stopped within 3 seconds, the
  part captured so far is kept.

Inspecting recording outcomes
-----------------------------

Inspect ``assets/manifest.csv`` for each recording's source, upload status, and
failure reason. Unavailable recordings remain listed without download links.
