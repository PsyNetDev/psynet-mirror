The Playwright hold tests no longer fail when a fast busy HTTP 503 is slowed by CI load; they still fail a busy request that waited for the participant's row lock.
