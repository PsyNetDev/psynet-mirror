Video answers now upload after submission in LocalStorage experiments with in-place navigation. Playback outside trials must wait for deposit and handle missing recordings. Replace `PageMaker(playback, time_estimate=5)` with:

```python
wait_for_recording(lambda participant: participant.assets["recording"]),
PageMaker(
    lambda participant: playback(participant)
    if participant.assets["recording"].deposited
    else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
    time_estimate=5,
),
```

Import `wait_for_recording` and `InfoPage` from `psynet.page`. A missing answer recording fails only its parent trial, without recapturing: immediately when the browser reports it unavailable (for example, camera access denied), otherwise once the browser stops uploading it for 2 minutes (for example, because it was closed) or 30 minutes after acceptance. Slow uploads are not failed: the browser renews them while it holds the recording, and a participant can be at most one recording page ahead of their uploads, waiting at **Next** on slow connections instead of building a backlog. Received recordings have 5 minutes, including queueing, to be stored. A submission whose reply was lost can be resent safely. Camera and screen streams are reused across consecutive recording pages and released once a page that does not record is shown. Uploads require an EBML header but are not decoded. Full-document transitions and recruiter exit wait for pending uploads to be received or fail; manual navigation warns while uploads remain pending. Bots upload their recordings through the same route as participants. Legacy navigation and other storage backends still upload with the answer, but now share the capture code: recordings are WebM only, and if capture fails, the page cannot be submitted until the participant reloads it to record again. The `video_recording` browser capability now requires WebM recording support, so browsers that can only record MP4 are screened out.
