Added admission points, so groups can take newcomers during a game without anyone waiting for them. With `SimpleGrouper(join_existing_groups=True, admit_newcomers="at_admission_point", target_group_size=...)`, a newcomer is a pending member: they hold a seat, but the quorum, barriers, leader, `GroupPrompt` and `group_seats` ignore them, and the group's other barriers let them straight through, until an admission point admits them. The admission points are a `GroupBarrier(admission_point=True, newcomer_max_wait=...)`, a synchronized trial maker's trial preparation (pass the trial maker `sync_group_newcomer_max_wait`), and a `Regrouper` split `within` the group type. An admission point waits up to the grouper's `top_up_wait` while the group is below `target_group_size`, `GroupBarrier(newcomer_page=...)` shows a page only to the members a visit admitted, and its `on_release` can take `admitted`. A pending member still waiting after `newcomer_max_wait`, or when the group stops taking top-ups or ends, is turned away with removal reason `"not_admitted"` and told so on their next page; they are never failed. `admit_newcomers="on_join"` keeps admitting newcomers at once; leaving `admit_newcomers` out with `join_existing_groups=True` warns and uses `"on_join"`. `SimpleGrouper(max_groups=...)` caps how many of a grouper's groups may be active at once. Each membership stores `admitted_at` and `admission_points_passed`, `group.pending_participants` lists pending members and `group.active_participants` only admitted ones, and `late_after` counts from a member's admission if that is later than the group's last barrier pass. A cue of a trial class with `sync_group_type` now raises an error for a participant without such a group unless the class sets `sync_group_optional = True`, and for a pending member. For example:

```python
SimpleGrouper(
    "society",
    initial_group_size=3,
    max_group_size=4,
    quorum=2,
    target_group_size=2,
    join_existing_groups=True,
    admit_newcomers="at_admission_point",
    below_quorum="continue_without_group",
)
...
GroupBarrier(
    id_="round_starts",
    group_type="society",
    admission_point=True,
    newcomer_max_wait=90,
    newcomer_page=PageMaker(history_page, time_estimate=20),
)
```
