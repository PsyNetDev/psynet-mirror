Audio answers from `AudioRecordControl` now upload after submission in LocalStorage experiments with in-place navigation, like video answers. Pages that play back or process a participant's recording outside a trial must wait for it and handle a missing recording. Replace a `wait_while` on `.deposited` followed by playback with:

```python
wait_for_recording(lambda participant: participant.assets["recording"]),
PageMaker(
    lambda participant: playback(participant)
    if participant.assets["recording"].deposited
    else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
    time_estimate=5,
),
```

A missing audio recording fails only its parent trial, without recapturing: immediately when the browser reports it unavailable, otherwise at the upload deadline. Trial analysis such as `analyze_recording` already waits for the recording. The built-in REPP tapping calibration prescreen now shows a message instead of playback when the practice recording is missing. Bots upload their `bot_response_media` through the same route as participants, so it must be a WAV file. Legacy navigation and other storage backends keep uploading audio with the answer.
