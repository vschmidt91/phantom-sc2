import warnings

import numpy as np
from scipy.linalg import expm
from scipy.stats import norm
from scipy.stats.qmc import Sobol


class XNES:
    def __init__(self, x0, sigma0):
        self.loc = np.asarray(x0, dtype=float)
        self.dim = self.loc.size
        self.scale = np.diag(sigma0)
        self._sampler = Sobol(self.dim, scramble=True)
        self._samples = None
        self._eta_scale = (3 + np.log(self.dim)) / (5 * np.sqrt(self.dim))

    @property
    def mu(self):
        return self.loc

    @property
    def sigma(self):
        return self.scale @ self.scale.T

    @property
    def expectation(self):
        return self.loc

    @property
    def covariance(self):
        return self.scale @ self.scale.T

    def ask(self, num_samples=None):
        num_samples = num_samples or (4 + int(3 * np.log(self.dim)))
        num_samples += num_samples % 2
        # Sobol sampling for powers of 2 has optimal space filling properties
        # this is mostly a theoretical concern, supress the warning here
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            u = self._sampler.random(num_samples // 2)
        z_half = norm.ppf(u).T
        z = np.hstack([z_half, -z_half])
        x = self.loc[:, None] + self.scale @ z
        self._samples = z
        return x

    def tell(self, ranking, eta=1.0):
        # rank samples
        num_samples = self._samples.shape[1]
        w = np.maximum(0, np.log(num_samples / 2 + 1) - np.log(np.arange(1, num_samples + 1)))
        w = w / np.sum(w) - (1 / num_samples)
        z_sorted = self._samples[:, ranking]

        # estimate gradient
        grad_mu = z_sorted @ w
        grad_scale = (z_sorted * w) @ z_sorted.T

        # update step
        self.loc += eta * (self.scale @ grad_mu)
        self.scale = self.scale @ expm(0.5 * eta * self._eta_scale * grad_scale)
