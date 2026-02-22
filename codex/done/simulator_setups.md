# Combat Setups

Now that both the sc2helper and custom simulators are mockable and executable directly, we want to:

1. Implement in phantom.mock: parametrized combat setups for both simulators
   - army1 at pos1, army2 at pos2, parametrized by distance
   - facing each other on a square with armies evenly lined up on opposing sides, parametrized by size
   - army1 evenly spaced on a circle, army2 at its center, parametrized by radius
   - crossing the T: vertical line against horizontal line, parametrized by size
2. Rewrite the comparison notebook (add v2) to use the combat setups
   - treat sc2helper results as ground truth
   - main results are scatter plots x=true, y=pred, color=parameter, subplot=setup
   - plot r2 scores as multiple line plots with x=parameter, y=score, color=true/pred, subplot=setup
3. Write a report below

# Notes

- collision should already be ignored
- for numpy simulator, assume all units are attacking
- make sure positions are used by both simulators
- use sc2helper mock directly but make sure it can also be run with resources/combat_sim/mock.pkl.xz

# Report

- Added `phantom/mock/combat_setups.py` with four parametrized setup generators shared by both simulators:
  - `distance`: army clusters centered at `(-d/2, 0)` and `(d/2, 0)`.
  - `square`: armies lined up on opposite square edges, parameterized by side `size`.
  - `circle`: army1 on circle perimeter, army2 at center, parameterized by `radius`.
  - `crossing_t`: army1 vertical stem and army2 horizontal bar, parameterized by `size`.
- Reworked `phantom/mock/combat_sim.py` dataset generation to be setup-driven and dual-simulator:
  - Uses `sc2helper` mock as ground truth (`true_outcome`).
  - Runs numpy Lanchester on the same unit stats and exact same positions (`pred_outcome`).
  - Sets numpy `attacking` to all unit tags.
  - Stores setup metadata per sample (`setup`, `parameter_name`, `parameter_value`) and true log outcomes.
- Added tests in `tests/test_mock_combat_setups.py`:
  - position-count invariants for all setup cases,
  - circle center placement for army2,
  - dataset row schema sanity for setup metadata and prediction fields.
- Added notebook `notebooks/combat_simulator_vs_dataset_v2.ipynb`:
  - can run direct via `generate_mock_combat_dataset(...)` (sc2helper mock) or load `resources/combat_sim/mock.pkl.xz`,
  - scatter subplots per setup with `x=true_outcome`, `y=pred_outcome`, color=`parameter_value`,
  - R2 line subplots per setup with `x=parameter`, `y=score`, color=`true/pred`.
- Added a third mock simulator baseline in `phantom/mock/hp_ratio_sim.py`:
  - `predict_outcome(units1, units2)` returns normalized HP ratio `(hp1 - hp2) / (hp1 + hp2)`.
  - `generate_mock_combat_dataset` now stores `pred_outcome_hp_ratio`.
  - notebook v2 integrates HP-ratio only in accuracy/R2 plots, not in scatter plots.
