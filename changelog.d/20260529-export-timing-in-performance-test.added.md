`psynet performance-test local` now measures export time: after each test run,
it runs `psynet export local` and includes the duration in the output. Use
`--no-export` to skip. Export time is included in `--json-output` results and
tracked as a new `track_export_time_s` metric in the ASV benchmark suite.
