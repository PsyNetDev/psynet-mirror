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

Import `wait_for_recording` and `InfoPage` from `psynet.page`. Missing or denied answer recordings fail only their parent trial at the upload deadline, without recapturing. Shared camera/screen tracks remain active across pages until the document closes. Uploads require an EBML header but are not decoded. Full-document transitions and recruiter exit wait for pending uploads to finish or reach their deadlines; manual navigation warns while uploads remain pending. Legacy navigation and other storage backends retain the existing answer-upload path.
