# CVXPYGEN

I have written a generator script that builds accelerated binaries for the assingment problem solvers (distribute.py).
The binaries turned out to be too large, but I didn't consider compression.
Also there should be a way to combine multiple cxvpygen outputs. test this out.

We want all the speed and all the elegance.
code generation hidden in scripts and wrapper method in distribute.py method that just works.

prepare sizes for 2^N with N=2..10 if possible
or maybe with golden ratio scaling? maybe there is something canonic.
inspect the distribute.py logic. mind the summation term used to hard-limit gas workers.

# ACTIVE TASK



# TASKS

1. rewrite the build script to generate a single packed, precompiled binary
2. write package common/distribute with /cpg and /hs subpackages for precompiled and cached JIT
3. rewrite distribute.py to expose the same interface as now and wire accordingly

# YOUR REPORT

## 2026-02-20 compile continuation (`log2-size <= 3`)

### Command used

`.\.venv\Scripts\python.exe scripts/compile_cvxpy.py --log2-size 3`

### Failures reproduced

1. `CMake is required...` even though CMake was installed in the venv.
2. After CMake was found: `ModuleNotFoundError: No module named 'harvest3'` from `cvxpygen.cpg.generate_code`.
3. After import path fix: `generic_type ... already registered!` when verifying `cpg_module` import in the same Python process.

### Fixes applied in `scripts/compile_cvxpy.py`

1. Added robust CMake resolution:
   - `--cmake` CLI override
   - `PHANTOM_CMAKE` env override
   - fallback to Python `cmake` wheel (`cmake.CMAKE_BIN_DIR`)
   - prepends resolved CMake directory to `PATH` for `cvxpygen` generated `setup.py` calls.
2. Added `build_root` to `sys.path` during `cpg.generate_code(...)` so `harvest3.cpg_solver` can be imported.
3. Changed post-build import validation to run in a subprocess (`sys.executable -c ... import cpg_module`) to avoid pybind11 type re-registration conflicts in the current process.

### Result

- Build now succeeds for `log2-size=3`.
- Artifacts produced:
  - `bin/cpg/cpg_module*.pyd`
  - `bin/cpg_bundle.zip`
- Runtime loader check succeeds:
  - `get_cpg_solver()` returns `CpgSolver harvest3 8`.

### Remaining note

- `setuptools` emits a deprecation warning about `fetch_build_eggs` from generated `setup.py`; this is from upstream CVXPYGEN template and not a functional blocker for now.

## 2026-02-20 naming + compression alignment

### Request

- Use LZMA compression.
- Keep folders and binaries named consistently with the problem name.

### Changes

1. `scripts/compile_cvxpy.py`
   - Output folder is now `bin/<problem_name>` (example: `bin/harvest3`), not `bin/cpg`.
   - Generated extension files are renamed from `cpg_module*` to `<problem_name>*` (example: `harvest3.cp312-win_amd64.pyd`).
   - Bundle format changed from zip to LZMA-compressed tarball: `bin/<problem_name>.tar.xz` (example: `bin/harvest3.tar.xz`).
   - Import verification now loads extension files by file path, so renamed binaries still validate.
2. `phantom/common/distribute/cpg/solver.py`
   - Loader now imports extension modules directly from file path.
   - Search order prefers `<folder_name>*.pyd`, then `cpg_module*.pyd`, then any `*.pyd` for compatibility.
   - This keeps support for both new naming and older artifacts.

### Validation (`log2-size=3`)

- Command: `.\.venv\Scripts\python.exe scripts/compile_cvxpy.py --log2-size 3`
- Result:
  - `bin/harvest3/harvest3.cp312-win_amd64.pyd`
  - `bin/harvest3.tar.xz`
- Runtime check:
  - `get_cpg_solver()` -> `CpgSolver harvest3 8`

## 2026-02-21 single directory bundle

### Request

- Keep every generated `harvestN` binary inside `bin/cpg`.
- Produce a single aggregate archive rather than per-solver bundles.
- Use the strongest available compression (xztar works, but keep the door open for future upgrades).

### Outcome

1. `scripts/compile_cvxpy.py`
   - Switches output to `bin/cpg`; all `harvestN*.pyd` artifacts now live side-by-side, so multiple sizes can coexist.
   - Builds cumulatively from `log2-size=1` through the requested `N`, ensuring `--log2-size 3` now produces `harvest1`, `harvest2`, and `harvest3` together.
   - Produces one LZMA tarball covering the entire folder: `bin/cpg.tar.xz`.
2. `phantom/common/distribute/cpg/solver.py`
   - Now scans `bin/cpg` for `harvestN*.pyd` binaries (highest `N` first) and imports those via file path, so the loader picks the largest available solver.

### Result

- Command: `.\.venv\Scripts\python.exe scripts/compile_cvxpy.py --log2-size 3`
- Files generated: `bin/cpg/harvest1.cp312-win_amd64.pyd`, `bin/cpg/harvest2.cp312-win_amd64.pyd`, `bin/cpg/harvest3.cp312-win_amd64.pyd`.
- Aggregate bundle: `bin/cpg.tar.xz`.

## 2026-02-21 wheel packaging for packed binaries

### Request

- Include packed CVXPYGEN binaries in the built wheel.

### Outcome

1. `scripts/compile_cvxpy.py`
   - Default `--output-dir` now points to `phantom/common/distribute/cpg/assets`.
   - Aggregate archive default path is now `phantom/common/distribute/cpg/assets/cpg.tar.xz`.
2. `pyproject.toml`
   - Adds `phantom/common/distribute/cpg/assets/cpg.tar.xz` to `[tool.poetry].include` for both `wheel` and `sdist`.
3. `phantom/common/distribute/cpg/assets/.gitkeep`
   - Ensures the assets directory exists in-repo.

### Note

- `scripts/build.py` clears `output_path` (`build/`) before extracting wheels; moving `cpg.tar.xz` under package assets avoids accidental deletion during `make zip`.

## 2026-02-21 CPG assignment correctness follow-up

### Request

- Dynamic loading is in place, but assignment results from CPG diverged from HighsPy.
- Expand tests and add a larger CPG-vs-HighsPy comparison.

### Outcome

1. `phantom/common/distribute/cpg/solver.py`
   - Fixed CPG cost parameter layout to Fortran order (`padded.ravel(order="F")`) to match CVXPYGEN matrix vectorization.
   - Added retry path when status is `maximum iterations reached` (temporarily disable warm starting, rerun once).
   - If still iteration-limited, keep the current iterate with a warning instead of raising immediately.
2. `phantom/common/distribute/__init__.py`
   - Replaced direct `argmax` decoding with a capacity-aware decoder:
     - Picks high-confidence assignments first (`x` descending, cost ascending),
     - Enforces per-target capacities,
     - Fills remaining sources by minimum finite cost under remaining capacity.
   - This avoids infeasible over-assignment when CPG returns a valid but fractional LP solution.
3. `tests/test_distribute.py`
   - Updated CPG selection mock expectations to current API shape.
   - Added deterministic larger backend comparison (`n=20`, `m=11`) that checks CPG and HighsPy row assignments and objective closeness.

### Validation

- Command: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_distribute.py -v`
- Result: `OK` (all tests in `test_distribute.py` passed).

## 2026-02-21 Windows absolute-path import failure in compile script

### Failure

- `scripts/compile_cvxpy.py --log2-size=5` failed inside `cvxpygen.cpg.generate_code` with:
  - `ModuleNotFoundError: No module named 'C:\\...\\assign1\\assign1'`
- Root cause: CVXPYGEN imports the wrapper as `importlib.import_module(f"{code_dir}.cpg_solver")`; absolute Windows paths are not valid module names.

### Fix

1. `scripts/compile_cvxpy.py`
   - Switched generation call to `wrapper=False`.
   - Added explicit `cpg.compile_python_module(str(build_dir))` immediately after generation.
   - Kept existing artifact copy + importability verification logic unchanged.

### Validation

- Command: `.\.venv\Scripts\python.exe scripts/compile_cvxpy.py --log2-size=1` (with `.venv\Scripts` on `PATH` so `cmake` is discoverable).
- Result: build completed, artifact copied to `phantom/common/distribute/cpg`, and `cpg.tar.xz` packed successfully.

## 2026-02-21 on-demand CPG archive extraction

### Request

- Simplify CPG binary loading so archive extraction is done lazily, only when a requested solver log is needed.

### Outcome

1. `phantom/common/distribute/cpg/solver.py`
   - Replaced eager archive unpacking (`extractall`) with targeted extraction for the requested `assignN` binary only.
   - Added archive log discovery without extraction, so `_available_solver_logs()` now includes both unpacked binaries and archive members.
   - Solver initialization now attempts direct load first, then lazily extracts `assignN` from `cpg.tar.xz` and retries import.
2. Extraction safety and behavior
   - Archive members are filtered to valid extension-module suffixes and matching `assignN` names.
   - Matching member contents are copied directly to `phantom/common/distribute/cpg` (no whole-archive unpack).

### Validation

- Command: `python -m compileall phantom/common/distribute/cpg/solver.py`
- Result: module compiled successfully.

## 2026-02-21 CPG vs HS path benchmark notebook

### Request

- Add a notebook benchmark that compares the `cpg` and `hs` paths in `phantom/common/distribute/__init__.py`.
- Use example problem sizes: `2, 4, 8, 16, 32`.

### Outcome

1. Added `notebooks/benchmark_distribute_cpg_vs_hs.ipynb`.
2. Notebook benchmarks both paths with matching random square cost matrices per size:
   - CPG path: `get_cpg_solver(...) -> solve(...) -> _decode_assignment(...)`
   - HS path: `get_hs_solver(...)` with the same padding logic used by `get_assignment_solver(...)`, then `solve(...) -> _decode_assignment(...)`
3. Benchmark includes:
   - Warmup rounds to avoid one-time init skew.
   - Mean and p95 latency (ms) for each path.
   - Objective delta tracking (`CPG - HS`) for sanity checks.
   - Optional table rendering via pandas and optional matplotlib line chart.

## 2026-02-21 benchmark notebook fallback for missing CPG sizes

### Issue

- Running `notebooks/benchmark_distribute_cpg_vs_hs.ipynb` failed with:
  - `RuntimeError: CPG solver unavailable for size 4x4`

### Notebook update

1. Reworked CPG execution path to preflight availability per size via `get_cpg_solver(...)`.
2. If a size has no loadable CPG solver, the benchmark now:
   - records `cpg_available=False`,
   - fills CPG-dependent metrics with `NaN`,
   - still benchmarks the HS path for that size,
   - prints the missing CPG size list once.

### Outcome

- Notebook now runs end-to-end even when only a subset of CPG binaries can be loaded in the current runtime.

## 2026-02-21 post-recompile CPG availability investigation

### Symptom observed

- Notebook benchmark failed at `size=4` with `CPG solver unavailable for size 4x4`.

### What was verified

1. Binary artifacts are present and recently rebuilt (`assign1..assign5.cp312-win_amd64.pyd`).
2. In isolated fresh Python processes, each binary imports and exposes the expected symbol:
   - `assign1 -> assign1_cpg_params`
   - `assign2 -> assign2_cpg_params`
   - `assign3 -> assign3_cpg_params`
   - `assign4 -> assign4_cpg_params`
   - `assign5 -> assign5_cpg_params`
3. In a single process, loading through `phantom.common.distribute.cpg.solver.get_cpg_solver(...)` fails for later logs after the first successful log load.
   - If `assign1` is loaded first, `assign2+` appear unavailable.
   - If `assign2` is loaded first, `assign1` and `assign3+` appear unavailable.

### Interpretation

- This is a runtime loading collision related to all generated extensions being loaded as `cpg_module` in-process.
- Recompilation succeeded; the issue is not missing binaries, but multi-module import behavior in one interpreter session.

### Impact on benchmark

- A single-kernel, ascending-size benchmark can misreport CPG as unavailable for some sizes even when binaries are valid.

## 2026-02-21 notebook scope narrowed to single CPG size

### Request

- Stop benchmarking multiple CPG module sizes.
- Restrict benchmark notebook to `N=32` only.

### Update

1. `notebooks/benchmark_distribute_cpg_vs_hs.ipynb`
   - `SIZES` changed from `[2, 4, 8, 16, 32]` to `[32]`.
   - Intro markdown updated to describe single-size (`32`) benchmarking.

### Reason

- Current CVXPYGEN multi-module loading is unreliable in one interpreter process; single-size benchmarking avoids that failure mode.

## 2026-02-21 cvxpygen deactivation

### Request

- Deactivate the whole `cvxpygen` module loading path.
- Keep compile scripts and solver wrapper files in the repo.
- Remove CI compile step.

### Update

1. `phantom/common/distribute/__init__.py`
   - Removed `get_cpg_solver` import.
   - Removed CPG-first branch in `get_assignment_solver(...)`.
   - HS solver path now always used.
2. `.github/workflows/build.yml`
   - Removed `Compile CVXPY solvers` step (`scripts/compile_cvxpy.py`).

### Outcome

- Runtime assignment no longer imports or loads CPG modules.
- CI no longer compiles CVXPYGEN artifacts.
- CPG scripts/wrappers remain in-tree for future reactivation.

## 2026-02-21 CVXPY `cp` solver package added

### Request

- Implement `phantom/common/distribute/cp` closely following `hs`, but define the problem with CVXPY and solve with warm starting.

### Outcome

1. Added `phantom/common/distribute/cp/solver.py`:
   - Introduces `CvxPySolver` with the same public interface shape as `HighsPySolver`:
     - `set_total(coeffs, limit)`
     - `solve(cost, limit)`
   - Keeps the same padding behavior as `hs` for incoming `cost` and `limit`.
   - Uses CVXPY `Parameter` objects for cost/limits/optional total constraint and solves with `warm_start=True`.
   - Includes per-size cache via `get_cp_solver(n, m)`.
2. Added `phantom/common/distribute/cp/__init__.py`:
   - Exports `CvxPySolver` and `get_cp_solver`.

### Validation

- Command: `.\.venv\Scripts\python.exe -m compileall phantom/common/distribute/cp/solver.py phantom/common/distribute/cp/__init__.py`
- Result: both files compile successfully.
