# ASV benchmark tiers

PsyNet splits ASV benchmarks into two CI tiers by directory:

- `fast/` contains hot-path microbenchmarks selected by the merge-request
  regression gate with `--bench "^fast\\."`.
- `slow/` contains end-to-end benchmarks that run on default-branch commits and
  feed the published benchmark log: debug-launch time for `static_big` (fastest
  of three launches per static-file profile), plus median request time and
  median queue delay for experiments under load. Wall-clock launches and load
  tests vary too much between runs for the merge-request gate's 1.25x factor.

Default-branch CI runs the full ASV suite with `asv continuous --factor 2`, so
both tiers contribute to regression checks on `master`. The factor is looser
than the merge-request gate (`1.25`) because the slow load-test medians are
noisier than the fast suite.
