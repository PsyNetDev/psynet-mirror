Fixed `Trial.cue` with `sync_group_type` for a member removed from their group during a round before their own cue reached it, for example by a barrier's `late_after` while the rest of the group was already playing. Their trial is now in that round, with their role and their removal reason as `sync_group_outcome`, so `group_round.trials` and exports list them, as for a member removed just after their trial started. Such a trial needs no `sync_group_optional = True`, and its `show_trial` needs no `GroupBarrier`, so to give players without a group a solo version, branch on `participant.in_sync_group(...)` rather than on `self.sync_group is None`:

```python
def show_trial(self, experiment, participant):
    if not participant.in_sync_group("team"):
        return self.solo_page()
    ...
```
