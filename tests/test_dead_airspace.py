import unittest
from dataclasses import dataclass

import numpy as np

from phantom.micro.dead_airspace import DeadAirspace


@dataclass(frozen=True)
class FakeUnit:
    can_attack_air: bool
    air_range: float
    type_id: object | None
    position: tuple[float, float]
    is_flying: bool


class DeadAirspaceTest(unittest.TestCase):
    def test_range_zero_matches_pathable_tiles(self):
        pathing = np.zeros((5, 5), dtype=bool)
        pathing[2, 2] = True
        dead_airspace = DeadAirspace(pathing, min_range=0, max_range=0)
        np.testing.assert_array_equal(dead_airspace._shootable_grids[0], pathing)

    def test_range_one_uses_circular_kernel(self):
        pathing = np.zeros((5, 5), dtype=bool)
        pathing[2, 2] = True
        dead_airspace = DeadAirspace(pathing, min_range=1, max_range=1)
        expected = np.zeros((5, 5), dtype=bool)
        expected[2, 2] = True
        expected[1, 2] = True
        expected[3, 2] = True
        expected[2, 1] = True
        expected[2, 3] = True
        np.testing.assert_array_equal(dead_airspace._shootable_grids[1], expected)

    def test_check_returns_false_when_unit_cannot_attack_air(self):
        pathing = np.ones((3, 3), dtype=bool)
        dead_airspace = DeadAirspace(pathing)
        attacker = FakeUnit(
            can_attack_air=False,
            air_range=10.0,
            type_id=None,
            position=(1.0, 1.0),
            is_flying=False,
        )
        target = FakeUnit(
            can_attack_air=True,
            air_range=0.0,
            type_id=None,
            position=(1.0, 1.0),
            is_flying=True,
        )
        self.assertFalse(dead_airspace.check(attacker, target))

    def test_check_returns_false_for_out_of_bounds_target(self):
        pathing = np.ones((3, 3), dtype=bool)
        dead_airspace = DeadAirspace(pathing)
        attacker = FakeUnit(
            can_attack_air=True,
            air_range=3.0,
            type_id=None,
            position=(1.0, 1.0),
            is_flying=False,
        )
        target = FakeUnit(
            can_attack_air=True,
            air_range=0.0,
            type_id=None,
            position=(9.0, 9.0),
            is_flying=True,
        )
        self.assertFalse(dead_airspace.check(attacker, target))

    def test_range_key_is_clamped_to_supported_values(self):
        pathing = np.ones((3, 3), dtype=bool)
        dead_airspace = DeadAirspace(pathing, min_range=0, max_range=5)
        self.assertEqual(dead_airspace._range_key(-1.0), 0)
        self.assertEqual(dead_airspace._range_key(2.9), 2)
        self.assertEqual(dead_airspace._range_key(100.0), 5)


if __name__ == "__main__":
    unittest.main()
