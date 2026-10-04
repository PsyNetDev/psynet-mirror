# ASV benchmark tiers

PsyNet splits ASV benchmarks into two CI tiers by directory:

- `fast/` contains benchmarks selected by the merge-request regression gate
  with `--bench "^fast\\."`, including hot paths and focused end-to-end checks.
- `slow/` contains end-to-end experiment benchmarks
  that run nightly on `master` (and as a manual job on `master` pipelines) and
  feed the published benchmark log.
  These benchmarks track median request time and median queue delay for an
  experiment that exercises async worker processes.

The nightly `master` pipeline runs the full ASV suite with `asv continuous --factor 2`, so
both tiers contribute to regression checks on `master`. The factor is looser
than the merge-request gate (`1.5`) because the slow load-test medians are
noisier than the fast suite.
