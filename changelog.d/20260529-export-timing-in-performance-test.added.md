`psynet performance-test local` now measures export time: after the last test,
it runs `psynet export local` and prints how long it took. Use `--no-export` to
skip. The final `--json-output` results include the export duration and any
export error on the last test's result. Export time is tracked as a new
`track_export_time_s` metric in the ASV benchmark suite.
