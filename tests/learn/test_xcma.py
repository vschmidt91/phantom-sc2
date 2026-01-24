import unittest
from functools import partial

import numpy as np
from scipy.optimize import rosen

from phantom.learn.xcma import XCMA


class XCMATest(unittest.TestCase):
    def test_basic(self):
        for f, solution in [
            (partial(np.linalg.norm, axis=0), (0.0, 0.0)),
            (rosen, (1, 1)),
        ]:
            with self.subTest(f=f, solution=solution):
                opt = XCMA([0.0, 0.0], 1.0)
                for _k in range(1000):
                    x = opt.ask()
                    fx = f(x)
                    opt.tell(fx)
                np.testing.assert_almost_equal(opt.m, solution)
