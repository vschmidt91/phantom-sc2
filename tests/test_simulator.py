import math
import unittest

from phantom.micro.simulator import ModelCombatSetup, NumpyLanchesterSimulator, SimulationUnit


class _StubParameters:
    time_distribution_lambda = 1.0
    lancester_dimension = 1.5
    enemy_range_bonus = 1.0


def _make_lings(num_units: int, position: tuple[float, float] = (0.0, 0.0), start_tag: int = 1) -> list[SimulationUnit]:
    return [
        SimulationUnit(
            tag=start_tag + i,
            is_enemy=False,
            is_flying=False,
            health=35,
            shield=0,
            ground_dps=10.0,
            air_dps=0.0,
            ground_range=0.1,
            air_range=0.0,
            radius=0.35,
            real_speed=4.13,
            position=position,
        )
        for i in range(num_units)
    ]


def _make_marines(
    num_units: int, center: tuple[float, float] = (0.0, 0.0), start_tag: int = 10_000
) -> list[SimulationUnit]:
    return [
        SimulationUnit(
            tag=start_tag + i,
            is_enemy=True,
            is_flying=False,
            health=45,
            shield=0,
            ground_dps=9.8,
            air_dps=9.8,
            ground_range=5.0,
            air_range=5.0,
            radius=0.375,
            real_speed=3.15,
            position=center,
        )
        for i in range(num_units)
    ]


class SimulatorTest(unittest.TestCase):
    def setUp(self):
        self.simulator = NumpyLanchesterSimulator(_StubParameters())

    def test_lings_vs_marines_runs(self):
        lings = _make_lings(20, position=(0.0, 0.0))
        marines = _make_marines(5, center=(5.0, 0.0))
        attacking = {u.tag for u in [*lings, *marines]}
        setup = ModelCombatSetup(units1=lings, units2=marines, attacking=attacking)

        result = self.simulator.simulate(setup)

        self.assertEqual(len(result.outcome_local), 25)
        self.assertTrue(math.isfinite(result.outcome_global))
        self.assertTrue(all(math.isfinite(value) for value in result.outcome_local.values()))

    def test_lings_starting_closer_improves_outcome(self):
        far_lings = _make_lings(20, position=(0.0, 0.0))
        close_lings = _make_lings(20, position=(0.0, 0.0), start_tag=100)
        far_marines = _make_marines(5, center=(10.0, 0.0))
        close_marines = _make_marines(5, center=(2.0, 0.0), start_tag=20_000)
        far_attacking = {u.tag for u in [*far_lings, *far_marines]}
        close_attacking = {u.tag for u in [*close_lings, *close_marines]}

        far_result = self.simulator.simulate(
            ModelCombatSetup(units1=far_lings, units2=far_marines, attacking=far_attacking)
        )
        close_result = self.simulator.simulate(
            ModelCombatSetup(units1=close_lings, units2=close_marines, attacking=close_attacking)
        )

        self.assertGreater(close_result.outcome_global, far_result.outcome_global)
