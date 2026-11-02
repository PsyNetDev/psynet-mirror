`psynet performance-test local` now measures export time: after the last test,
it runs `psynet export local` on the database the tests filled and prints how
long it took and how many participants and responses it exported. Use
`--no-export` to skip. The `--json-output` file records it in a top-level
`export` object with `duration_s`, `error` and the exported table sizes
(`db_rows`). Export time is tracked as a new `track_export_time_s` metric in
the ASV benchmark suite.
