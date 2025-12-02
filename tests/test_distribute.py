import unittest

import numpy as np

from phantom.common.distribute import get_assignment_solver


class DistributeTest(unittest.TestCase):
    def setUp(self):
        pass

    def test_distribute(self):
        problem = get_assignment_solver(3, 3)
        cost = np.array(
            [
                [0, 1, 1],
                [1, 0, 1],
                [1, 1, 0],
            ],
            dtype=float,
        )
        limit = np.array([1, 1, 1], dtype=float)
        solution = np.array(
            [
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
            ]
        )
        result = problem.solve(cost, limit)
        np.testing.assert_almost_equal(result, solution)

    def test_negative(self):
        problem = get_assignment_solver(3, 1)
        cost = np.array(
            [
                [-1],
                [1],
                [1],
            ],
            dtype=float,
        )
        limit = np.array([3], dtype=float)
        solution = np.array(
            [
                [1],
                [1],
                [1],
            ]
        )
        result = problem.solve(cost, limit)
        np.testing.assert_almost_equal(result, solution)

    def test_padding(self):
        cost = np.array(
            [
                [0, 1, 1],
                [1, 0, 1],
                [1, 1, 0],
            ],
            dtype=float,
        )
        limit = np.array([1, 1, 1], dtype=float)
        solution = get_assignment_solver(3, 3).solve(cost, limit)
        solution_padded = get_assignment_solver(8, 8).solve(cost, limit)
        np.testing.assert_almost_equal(solution_padded, solution)

    def tearDown(self):
        pass
