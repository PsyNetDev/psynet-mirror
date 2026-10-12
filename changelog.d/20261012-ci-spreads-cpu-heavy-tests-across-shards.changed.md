CI test sharding now puts each CPU-heavy test listed in `CPU_HEAVY_ITEMS` (`psynet/dev/ci_tests.py`) on a different shard, so two of them no longer compete for the same 2-vCPU runner.
