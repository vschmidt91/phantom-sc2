# CVXPYGEN

I have written a generator script that builds accelerated binaries for the assingment problem solvers (distribute.py).
The binaries turned out to be too large, but I didn't consider compression.
Also there should be a way to combine multiple cxvpygen outputs. test this out.

We want all the speed and all the elegance.
code generation hidden in scripts and wrapper method in distribute.py method that just works.

prepare sizes for 2^N with N=2..10 if possible
or maybe with golden ratio scaling? maybe there is something canonic.
inspect the distribute.py logic. mind the summation term used to hard-limit gas workers.

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

