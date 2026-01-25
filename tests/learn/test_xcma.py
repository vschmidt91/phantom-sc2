import unittest
from functools import partial

import numpy as np
from scipy.optimize import rosen
from sklearn.datasets import make_regression

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
                    z, x = opt.ask()
                    opt.tell(z, np.argsort(f(x)))
                np.testing.assert_almost_equal(opt.loc, solution)

    def test_regression(self):
        for seed in range(10):
            with self.subTest(seed=seed):
                d = 30
                X, y_true, coef_true = make_regression(n_samples=1000, n_features=d, coef=True, random_state=seed)

                opt = XCMA(x0=np.zeros(d), sigma0=np.ones(d))
                while True:
                    z, x = opt.ask(rng=np.random.default_rng(seed))  # Shape (n_pop, 50)
                    rewards = []
                    for w in x.T:
                        y_pred = X @ w
                        mse = np.mean((y_true - y_pred) ** 2)
                        rewards.append(mse)

                    if opt.tell(z, np.argsort(rewards)):
                        break

                y = X @ opt.loc
                np.testing.assert_almost_equal(opt.loc, coef_true, decimal=1)
                np.testing.assert_almost_equal(y, y_true, decimal=1)
