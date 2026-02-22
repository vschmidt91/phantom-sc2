# Simulator Testbed

simulator should be more maintainable and comparable.
add a simple unit model for simulation that we can mock.
I need a way to run through the numpy lanchester model on some basic scenarios (20 lings vs 5 marines as first example). leave out the sc2_helper stuff for that, it operates on python-sc2 units.

# Report
- Extracted a pure numpy combat path into `NumpyLanchesterSimulator` that works on a simple dataclass (`SimulationUnit`) and `ModelCombatSetup`.
- Kept the existing `CombatSimulator.simulate(CombatSetup)` API intact for production usage.
- Added `CombatSimulator.simulate_model(ModelCombatSetup)` so tests and experiments can bypass `sc2_helper`.
- Moved `sc2_helper` import to runtime and made it optional; if unavailable, the simulator returns the numpy global/local result.
- Added `tests/test_simulator.py` with a mock scenario for `20 lings vs 5 marines` and a distance sensitivity check.
- Updated simulator tests to spawn armies as two points only: all own units at point A and all enemy units at point B.
- Added `notebooks/lanchester_distance_vs_outcome.ipynb` to visualize initial group distance vs `outcome_global` for `20 lings vs 5 marines`.
