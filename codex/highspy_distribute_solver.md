## User Input
- Verify and improve the HiGHS solver in `phantom/common/distribute.py`.
- Use dual simplex explicitly.
- Avoid padding with `inf`; disable invalid padded assignments via `ub = 0`.
- Suggest and apply additional sensible improvements.

## Report
- Forced HiGHS to simplex mode with explicit dual simplex (`solver="simplex"`, `simplex_strategy=1`).
- Replaced `np.inf` objective padding with structural masking through per-variable upper bounds:
  - real rows can use real and padded columns (padded columns are dummy spill targets)
  - padded rows can use only padded columns
  - all forbidden arcs now have `ub=0`.
- Kept padded costs finite (`0.0`) and made active-cost validation strict (`finite` only).
- Hardened inputs:
  - shape checks for `cost` and `limit` against compiled solver dimensions
  - non-negative and finite limit validation.
- Adjusted padded target capacity default from `n` to `self.n` to avoid infeasibility when rounded source padding exceeds runtime `n`.
- Added explicit HiGHS status checks (`passModel`, `run`, and model optimality) with clear runtime errors.
- Updated assignment extraction in `distribute` to skip rows with no mass on real targets (rows absorbed by padded dummy targets).
- Validation:
  - `make fix`
  - `make check`
  - runtime smoke test through `distribute(...)`.
