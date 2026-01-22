import unittest

import numpy as np

from phantom.learn.parameters import ParameterOptimizer, Prior


class ParametersTest(unittest.TestCase):
    def setUp(self):
        pass

    def test_evolution(self):
        parameters = ParameterOptimizer(3)
        p1 = parameters.add("param1", Prior(0, 1e-3))
        p2 = parameters.add("param2", Prior(1, 1e3))

        def compare_fn(a, b):
            return a - b

        parameters.set_values_from_best()
        np.testing.assert_equal(p1.value, 0)
        np.testing.assert_equal(p2.value, 1)

        parameters.set_values_from_latest()
        parameters.tell_result(2, compare_fn)
        parameters.set_values_from_latest()
        parameters.tell_result(1, compare_fn)
        parameters.set_values_from_latest()
        parameters.tell_result(5, compare_fn)
        parameters.set_values_from_latest()
        parameters.tell_result(4, compare_fn)

    def test_save_load(self):
        seed = 42
        ps = ParameterOptimizer(4, np.random.default_rng(seed))
        qs = ParameterOptimizer(4, np.random.default_rng(seed))

        def compare_fn(a, b):
            return a - b

        p1 = ps.add("param1", Prior(0, 1e-3))
        p2 = ps.add("param2", Prior(1, 1e3))

        q1 = qs.add("param1", Prior(0, 1e-3))
        q2 = qs.add("param2", Prior(1, 1e3))

        ps.set_values_from_latest()
        ps.tell_result(2, compare_fn)

        qs.set_values_from_latest()
        qs.tell_result(2, compare_fn)

        p_state = ps.get_state()
        q_state = qs.get_state()

        np.testing.assert_equal(p_state.loc, q_state.loc)
        np.testing.assert_equal(p_state.scale, q_state.scale)
        np.testing.assert_equal(p_state.batch_x, q_state.batch_x)
        np.testing.assert_equal(p_state.batch_z, q_state.batch_z)
        np.testing.assert_equal(p_state.batch_results, q_state.batch_results)
        np.testing.assert_equal(p_state.names, q_state.names)

        qs = ParameterOptimizer(4)
        q1 = qs.add("param1", Prior(0, 1e-3))
        q2 = qs.add("param2", Prior(1, 1e3))

        qs.load_state(q_state)

        ps.set_values_from_latest()
        qs.set_values_from_latest()

        self.assertEqual(p1.value, q1.value)
        self.assertEqual(p2.value, q2.value)

        ps.tell_result(3, compare_fn)
        qs.tell_result(3, compare_fn)

        q_state = qs.get_state()
        qs = ParameterOptimizer(4)
        q1 = qs.add("param1", Prior(0, 1e-3))
        q2 = qs.add("param2", Prior(1, 1e3))

        qs.load_state(q_state)

        ps.set_values_from_latest()
        qs.set_values_from_latest()

        self.assertEqual(p1.value, q1.value)
        self.assertEqual(p2.value, q2.value)

    def tearDown(self):
        pass
