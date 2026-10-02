Closing a database session without committing now discards the timeline hold wakes it queued, so a later commit on the same session no longer sends them.
