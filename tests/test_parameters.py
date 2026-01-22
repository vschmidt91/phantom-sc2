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
        params = ParameterOptimizer(4)

        def compare_fn(a, b):
            return a - b

        p1 = params.add("param1", Prior(0, 1e-3))
        p2 = params.add("param2", Prior(1, 1e3))
        params.set_values_from_latest()
        params.tell_result(2, compare_fn)
        state = params.get_state()

        params.add("param3", Prior(2, 1))
        params.load_state(state)
        params.set_values_from_best()
        self.assertEqual(p1.value, state.loc[0])
        self.assertEqual(p2.value, state.loc[1])

        params.set_values_from_latest()
        params.tell_result(4, compare_fn)

    def tearDown(self):
        pass
