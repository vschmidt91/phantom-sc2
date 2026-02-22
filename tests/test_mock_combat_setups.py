import unittest

from phantom.mock.combat_setups import positions_for_setup, setup_cases
from phantom.mock.combat_sim import generate_mock_combat_dataset
from phantom.mock.hp_ratio_sim import predict_outcome


class MockCombatSetupsTest(unittest.TestCase):
    def test_positions_match_army_sizes(self):
        n1 = 7
        n2 = 5
        for case in setup_cases():
            positions1, positions2 = positions_for_setup(case.name, case.parameter_value, n1, n2)
            self.assertEqual(n1, len(positions1))
            self.assertEqual(n2, len(positions2))

    def test_circle_setup_places_enemy_at_center(self):
        positions1, positions2 = positions_for_setup("circle", 6.0, 8, 4)
        self.assertEqual(8, len(positions1))
        self.assertTrue(all(position == (0.0, 0.0) for position in positions2))

    def test_dataset_contains_setup_metadata_and_predictions(self):
        dataset = generate_mock_combat_dataset(
            simulation_count=4,
            spawn_count=3,
            use_position=True,
            seed=1337,
        )
        self.assertEqual(4, len(dataset))
        for row in dataset:
            self.assertIn("setup", row)
            self.assertIn("parameter_name", row)
            self.assertIn("parameter_value", row)
            self.assertIn("true_outcome", row)
            self.assertIn("pred_outcome", row)
            self.assertIn("pred_outcome_hp_ratio", row)

    def test_hp_ratio_sim(self):
        class StubUnit:
            def __init__(self, health: float, shield: float):
                self.health = health
                self.shield = shield

        own = [StubUnit(100, 0), StubUnit(50, 25)]
        enemy = [StubUnit(100, 0)]
        self.assertAlmostEqual(0.2727272727, predict_outcome(own, enemy), places=8)
