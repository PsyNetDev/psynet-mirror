Barriers' and groupers' `waiting_logic_expected_repetitions` is deprecated and raises a `FutureWarning`; pass `expected_wait` (in seconds) instead. `expected_wait` now also works with `waiting_logic`, which is then expected to repeat often enough to fill that time.

```python
SimpleGrouper("quorum", initial_group_size=3, waiting_logic=filler, expected_wait=30)
```
