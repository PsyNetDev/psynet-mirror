# ASV benchmark tiers

PsyNet splits ASV benchmarks into two CI tiers by directory:

- `fast/` contains hot-path microbenchmarks selected by the merge-request
  regression gate with `--bench "^fast\\."`.
- `slow/` contains end-to-end benchmarks that run nightly on `master` (and as a
  manual job on `master` pipelines) and feed the published benchmark log:
  debug-launch time for `static_big` (fastest of three launches per static-file
  profile), median request time and median queue delay for experiments
  under load, and the barrier poller's idle sweep time at 100 and 300
  waiting visits. Wall-clock launches, load tests and database timings vary
  too much between runs for the merge-request gate's 1.25x factor.

The nightly `master` pipeline runs the full ASV suite with `asv continuous --factor 2`, so
both tiers contribute to regression checks on `master`. The factor is looser
than the merge-request gate (`1.25`) because the slow load-test medians are
noisier than the fast suite. That job is allowed to fail, so slow-tier results
(including debug-launch time) are tracked rather than gating merges.
