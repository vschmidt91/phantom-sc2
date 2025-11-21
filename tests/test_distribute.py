import unittest

import numpy as np

from phantom.common.distribute import _get_problem


class DistributeTest(unittest.TestCase):
    def setUp(self):
        pass

    def test_distribute(self):
        problem = _get_problem(3, 3)
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
        problem = _get_problem(3, 1)
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
        solution = _get_problem(3, 3).solve(cost, limit)
        solution_padded = _get_problem(8, 8).solve(cost, limit)
        np.testing.assert_almost_equal(solution_padded, solution)

    def tearDown(self):
        pass
