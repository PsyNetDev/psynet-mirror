Recording video and handling uploads
====================================

Answer recordings upload independently of page navigation. Wait for deposit and
provide a fallback when a later page needs the recording.

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
uploads still complete before navigation. In-place experiments drain pending
uploads before full-page
transitions and recruiter exit, displaying an upload message; failures and the
original deadlines bound this wait. Deliberate early-exit and error redirects
can abandon pending uploads without an additional browser warning.

Shared camera and screen tracks stay active across pages until the document closes.
Clips with audio disabled stop and remove cached audio tracks, even when the shared
camera was previously used with audio. In the asynchronous path, denied capture
saves the answer and fails its parent trial at the upload deadline instead of throwing a
permission error. Legacy upload behavior is unchanged.

Uploads must begin with the WebM/EBML header. This rejects obvious non-media input;
it does not decode the file or guarantee that the recording is playable.

The first answer screen recording displays a **Share screen** button before task
startup. Compatible later pages reuse the stream; a full reload requires a new
permission decision. Skipping capture follows the missing-upload policy above.

Inspecting recording outcomes
-----------------------------

Inspect ``assets/manifest.csv`` for each recording's source, capture outcome,
upload status, and failure reason. Unavailable recordings remain listed without
download
links; partial clips are identified by their capture outcome.
