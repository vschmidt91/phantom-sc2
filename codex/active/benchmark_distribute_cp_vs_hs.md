# Benchmark distribute cp vs hs

## User request
- Add a benchmark notebook comparing:
`phantom/common/distribute/cp`
`phantom/common/distribute/hs`
on random assignment problems for `N = 2, 4, 8, 16, 32, 64`.

## Implementation
- Added notebook: `notebooks/benchmark_distribute_cp_vs_hs.ipynb`.
- Benchmarks both solver backends with:
`PROBLEMS_PER_SIZE = 40`
`WARMUP_ROUNDS = 10`
`SEED = 7`
- Uses square random cost matrices (`N x N`) and per-column capacity limit of `1`.
- Reports:
`cp_ms_mean`, `cp_ms_p95`, `hs_ms_mean`, `hs_ms_p95`,
`speedup_hs_over_cp`,
`avg_obj_delta_cp_minus_hs`,
`assignment_mismatches`.
- Includes optional pandas table and matplotlib timing plot.
