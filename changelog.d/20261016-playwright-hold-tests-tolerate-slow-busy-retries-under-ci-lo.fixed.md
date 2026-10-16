The Playwright hold tests no longer fail when a busy HTTP 503 is slowed by CI load; a unit test checks that hold-resume requests use `NOWAIT` instead.
