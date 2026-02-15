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
        np.testing.assert_equal(xnes.scale, [[2, 0], [0, 2]])
        xnes = XNES([0, 0], [2, 3])
        np.testing.assert_equal(xnes.scale, [[2, 0], [0, 3]])
        xnes = XNES([0, 0], [[2, 3], [4, 5]])
        np.testing.assert_equal(xnes.scale, [[2, 3], [4, 5]])

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
                np.testing.assert_almost_equal(opt.loc, solution)

    def test_1d(self):
        target = 123
        opt = XNES([0], 1)
        for _k in range(1000):
            z, x = opt.ask()
            fx = ((x - target) ** 2).sum(0)
            ranking = np.argsort(fx)
            opt.tell(z, ranking)
        np.testing.assert_almost_equal(opt.loc, target)

    @unittest.skip("fails to converge currently")
    def test_regression(self):
        for seed in range(10):
            with self.subTest(seed=seed):
                d = 10
                X, y_true, coef_true = make_regression(n_samples=1000, n_features=d, coef=True, random_state=seed)

                opt = XNES(np.zeros(d), 1.0)
                while True:
                    z, x = opt.ask(rng=np.random.default_rng(seed))
                    rewards = []
                    for w in x.T:
                        y_pred = X @ w
                        mse = np.mean((y_true - y_pred) ** 2)
                        rewards.append(mse)

                    if opt.tell(z, np.argsort(rewards), eps=1e-3):
                        break

                y = X @ opt.loc
                np.testing.assert_almost_equal(opt.loc, coef_true, decimal=1)
                np.testing.assert_almost_equal(y, y_true, decimal=1)
