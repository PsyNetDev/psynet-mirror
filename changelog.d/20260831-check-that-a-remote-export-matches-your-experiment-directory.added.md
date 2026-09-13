Before transferring anything, `psynet export` now asks the deployment to
identify itself and compares it with your experiment directory. Running the
command from the wrong folder stops the export instead of overwriting your
export directory with another experiment's data. A differing Git commit, or
uncommitted changes on either side, produces a warning and a confirmation
prompt; pass `--allow-project-mismatch` to proceed in a non-interactive shell.
Exports also declare an `export_format_version` in `manifest.json`, and PsyNet
refuses an archive it cannot read rather than downloading it first.
