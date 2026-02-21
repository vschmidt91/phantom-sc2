import unittest
from collections import Counter
from unittest.mock import patch

import numpy as np
import phantom.common.distribute as distribute_module

from phantom.common.distribute import distribute, get_assignment_solver
from phantom.common.distribute.cpg.solver import get_cpg_solver
from phantom.common.distribute.hs.solver import get_hs_solver


class AssignmentSolverSelectionTest(unittest.TestCase):
    def test_prefers_cpg_solver_when_it_is_available(self):
        cpg_solver = object()

        with (
            patch.object(distribute_module, "get_cpg_solver", return_value=cpg_solver) as get_cpg_solver,
            patch.object(distribute_module, "get_hs_solver") as get_hs_solver,
        ):
            solver = get_assignment_solver(8, 8)

        self.assertIs(solver, cpg_solver)
        get_cpg_solver.assert_called_once_with(8, 8, 128)
        get_hs_solver.assert_not_called()

    def test_falls_back_to_highspy_solver_with_resolution_padding(self):
        hs_solver = object()

        with (
            patch.object(distribute_module, "get_cpg_solver", return_value=None),
            patch.object(distribute_module, "get_hs_solver", return_value=hs_solver) as get_hs_solver,
        ):
            solver = get_assignment_solver(9, 3)

        self.assertIs(solver, hs_solver)
        get_hs_solver.assert_called_once_with(16, 8)


class AssignmentSolverIntegrationTest(unittest.TestCase):
    def test_solver_finds_diagonal_minimum(self):
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
        expected = np.array(
            [
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
            ],
            dtype=float,
        )

        result = problem.solve(cost, limit)

        np.testing.assert_allclose(result, expected)

    def test_solver_respects_column_limits(self):
        problem = get_assignment_solver(3, 1)
        cost = np.array([[-1], [1], [1]], dtype=float)
        limit = np.array([3], dtype=float)
        expected = np.array([[1], [1], [1]], dtype=float)

        result = problem.solve(cost, limit)

        np.testing.assert_allclose(result, expected)

    def test_solver_padding_does_not_change_solution(self):
        cost = np.array(
            [
                [0, 1, 1],
                [1, 0, 1],
                [1, 1, 0],
            ],
            dtype=float,
        )
        limit = np.array([1, 1, 1], dtype=float)

        unpadded = get_assignment_solver(3, 3).solve(cost, limit)
        padded = get_assignment_solver(8, 8).solve(cost, limit)

        np.testing.assert_allclose(padded, unpadded)

    def test_a_cpg_matches_highspy_on_large_problem(self):
        n = 20
        m = 11
        rng = np.random.default_rng(7)
        cost = rng.uniform(-2.0, 5.0, size=(n, m))
        limit = np.full(m, np.ceil(n / m), dtype=float)

        cpg_solver = get_cpg_solver(n, m, 128)
        if cpg_solver is None:
            self.skipTest("No compiled CPG solver available in this environment")

        hs_solver = get_hs_solver(cpg_solver.problem_size, cpg_solver.problem_size)
        cpg_solver.set_total(np.zeros(m), 0)
        hs_solver.set_total(np.zeros(m), 0)

        cpg = cpg_solver.solve(cost, limit)
        hs = hs_solver.solve(cost, limit)

        np.testing.assert_array_equal(cpg.argmax(axis=1), hs.argmax(axis=1))
        self.assertLessEqual(abs(float(np.sum(cost * cpg) - np.sum(cost * hs))), 1e-1)


class DistributeTest(unittest.TestCase):
    def test_returns_empty_mapping_for_empty_source_or_target(self):
        self.assertEqual(distribute([], ["x"], np.zeros((0, 1))), {})
        self.assertEqual(distribute(["a"], [], np.zeros((1, 0))), {})

    def test_default_max_assigned_balances_assignments(self):
        sources = ["a", "b", "c"]
        targets = ["x", "y"]
        cost = np.array(
            [
                [0.0, 10.0],
                [0.0, 10.0],
                [0.0, 10.0],
            ],
            dtype=float,
        )

        assignment = distribute(sources, targets, cost)

        counts = Counter(assignment.values())
        self.assertEqual(len(assignment), len(sources))
        self.assertEqual(counts["x"], 2)
        self.assertEqual(counts["y"], 1)

    def test_vector_max_assigned_is_respected(self):
        sources = ["a", "b"]
        targets = ["x", "y"]
        cost = np.array(
            [
                [0.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        )

        assignment = distribute(sources, targets, cost, max_assigned=np.array([0, 2], dtype=float))

        self.assertEqual(assignment["a"], "y")
        self.assertEqual(assignment["b"], "y")

    def test_sticky_assignment_overrides_cost(self):
        sources = ["a", "b"]
        targets = ["x", "y"]
        cost = np.array(
            [
                [0.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        )

        assignment = distribute(
            sources,
            targets,
            cost,
            max_assigned=1,
            sticky={"a": "y", "b": "x"},
            sticky_cost=0.0,
        )

        self.assertEqual("y", assignment["a"])
        self.assertEqual("x", assignment["b"])

    def test_sticky_ignores_missing_target(self):
        assignment = distribute(
            ["a"],
            ["x"],
            np.array([[1.0]], dtype=float),
            sticky={"a": "missing"},
            sticky_cost=0.0,
        )

        self.assertEqual("x", assignment["a"])

    def test_nan_cost_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "NaN values are not valid"):
            distribute(["a"], ["x"], np.array([[np.nan]], dtype=float))

    def test_infinite_cost_results_in_unassigned_source(self):
        assignment = distribute(
            ["a"],
            ["x"],
            np.array([[np.inf]], dtype=float),
        )

        self.assertEqual(assignment, {})
