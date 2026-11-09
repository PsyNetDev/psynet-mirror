`trial.answer` now holds the answer so far while a trial's pages are being answered, the same value as `participant.answer`, instead of staying `None` until the trial ends. A `GroupBarrier` inside `show_trial` can therefore read each member's answer in `on_release` from `trial.answer`, without `save_answer` and `participant.var`:

```python
@classmethod
def score_room(cls, trials, node):
    node.var.picks = [t.answer for t in trials]  # None: the page ran out of time
```

When the trial ends, `trial.answer` is set to the result of `format_answer` as before.
