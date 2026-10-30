`psynet performance-test local` now measures export time: after each test run,
it runs `psynet export local` and includes the duration in the output (with
`--existing` and multiple bot counts, the export runs once at the end). Use
`--no-export` to skip. The final `--json-output` results include the export
duration and any export error. Export time is tracked as a new
`track_export_time_s` metric in the ASV benchmark suite.
