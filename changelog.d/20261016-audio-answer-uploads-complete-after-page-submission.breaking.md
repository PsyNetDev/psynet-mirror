Audio answers from `AudioRecordControl` now upload after submission in LocalStorage experiments with in-place navigation, like video answers. Any later page that plays back or processes the recording, including a later page of the same trial (other than feedback), must wait for it and handle a missing recording. Replace a `wait_while` on `.deposited` followed by playback with:

```python
wait_for_recording(lambda participant: participant.assets["recording"]),
PageMaker(
    lambda participant: playback(participant)
    if participant.assets["recording"].deposited
    else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
    time_estimate=5,
),
```

A missing audio recording fails only its parent trial, without recapturing: immediately when the browser reports it unavailable, otherwise when its upload expires. Trial analysis such as `analyze_recording` and trial feedback already wait for the recording. The warm-up playback in the built-in `FreeTappingRecordTest` prescreen now shows a message when the practice recording is missing. Subclasses of `AudioRecordControl` or `VideoRecordControl` that override `format_answer` or `macro` keep uploading with the answer, because they may read the recording bytes there. Bots upload their `bot_response_media` through the same route as participants, so it must be a WAV file. Legacy navigation and other storage backends keep uploading audio with the answer.
