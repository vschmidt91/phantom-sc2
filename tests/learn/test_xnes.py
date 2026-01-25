import unittest
from functools import partial

import numpy as np
from scipy.optimize import rosen
from sklearn.datasets import make_regression

from phantom.learn.xnes import XNES


class XNESTest(unittest.TestCase):
    def setUp(self):
        pass

    def test_args(self):
        xnes = XNES([0, 0], 2)
        np.testing.assert_equal(xnes.sigma, [[4, 0], [0, 4]])
        xnes = XNES([0, 0], [2, 3])
        np.testing.assert_equal(xnes.sigma, [[4, 0], [0, 9]])
        xnes = XNES([0, 0], [[2, 3], [4, 5]])
        np.testing.assert_equal(xnes.sigma, [[13, 23], [23, 41]])

    def test_basic(self):
        for f, solution in [
            (partial(np.linalg.norm, axis=0), (0, 0)),
            (rosen, (1, 1)),
        ]:
            with self.subTest(f=f, solution=solution):
                opt = XNES([0, 0], [1, 1])
                for _k in range(1000):
                    z, x = opt.ask()
                    fx = f(x)
                    ranking = np.argsort(fx)
                    opt.tell(z, ranking)
                np.testing.assert_almost_equal(opt.expectation, solution)

    def test_1d(self):
        target = 123
        opt = XNES([0], 1)
        for _k in range(1000):
            z, x = opt.ask()
            fx = ((x - target) ** 2).sum(0)
            ranking = np.argsort(fx)
            opt.tell(z, ranking)
        np.testing.assert_almost_equal(opt.expectation, target)

    @unittest.skip("fails to converge currently")
    def test_regression(self):
        for seed in range(10):
            with self.subTest(seed=seed):
                d = 2
                X, y_true, coef_true = make_regression(n_samples=100, n_features=d, coef=True, random_state=seed)

                opt = XNES(x0=np.zeros(d), sigma0=np.ones(d))
                while True:
                    z, x = opt.ask(rng=np.random.default_rng(seed))  # Shape (n_pop, 50)
                    rewards = []
                    for w in x.T:
                        y_pred = X @ w
                        mse = np.mean((y_true - y_pred) ** 2)
                        rewards.append(mse)

                    if opt.tell(z, np.argsort(rewards), eta=0.3):
                        break

                y = X @ opt.expectation
                np.testing.assert_almost_equal(opt.expectation, coef_true, decimal=1)
                np.testing.assert_almost_equal(y, y_true, decimal=1)
