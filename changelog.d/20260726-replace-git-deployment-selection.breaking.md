Replaced Git and `.dockerignore` deployment file selection with explicit
`deploy.toml` policies as a breaking PsyNet cutover. PsyNet scaffolds
`deploy.toml` (and creates it automatically when missing without overwriting
an existing file). The first debug, test, or deploy after an auto-created
policy stops once so authors can review the plan; Git-ignored files may still
be deployed after that review. Leftover generated `.dockerignore` files are removed on
debug, deploy, scaffold, and prune; custom copies are preserved by scaffold
commands but must be migrated to `deploy.toml` and removed before debug or
deployment.
The generated experiment `docker/` helper scripts are no longer scaffolded
and recognized generated copies are deleted by `psynet scripts update` and on
debug/deploy; customized helpers and `docker/` symlinks are preserved.
`psynet setup --docker` is removed; use `psynet setup` then
`psynet debug local --docker`. Membership no longer depends on Git visibility,
while Git remains required to identify the source commit and dirty state.
Experiments ignored by a containing repository must run `psynet setup` to
create a dedicated repository. The 256 MB package-size check now measures the
deployment plan. Deprecated source-export compatibility options emit warnings
when used.
Stock excludes include virtualenv directories (`env`, `.venv`). Heroku
deploys no longer ask authors to remove `.deploy` from `.gitignore`.
This requires Dallinger with `deploy.toml` (master after
[Dallinger #9680](https://github.com/Dallinger/Dallinger/pull/9680);
not yet in a 12.3.x release), Python 3.11 or later, and a POSIX filesystem.
