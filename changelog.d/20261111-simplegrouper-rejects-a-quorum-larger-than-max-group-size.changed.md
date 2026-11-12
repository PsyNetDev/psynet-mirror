`SimpleGrouper` now raises a `ValueError` when `quorum` is larger than `max_group_size`, since such a group could never reach its quorum.
