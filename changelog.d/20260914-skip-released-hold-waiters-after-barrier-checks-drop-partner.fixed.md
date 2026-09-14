Released hold waiters are skipped one at a time after the barrier check commits, so a partner GET /timeline can lock its own row instead of waiting out timeline_lock_timeout_seconds.
