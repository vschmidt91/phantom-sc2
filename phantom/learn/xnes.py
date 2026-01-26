from functools import cmp_to_key

import numpy as np
from numpy.linalg import cond, norm
from scipy.linalg import expm, qr


def ranking_from_comparer(population, compare_func, maximize=True):
    def idx_compare(i, j):
        return compare_func(population[i], population[j])

    indices = sorted(range(len(population)), key=cmp_to_key(idx_compare), reverse=maximize)
    return indices


class XNES:
    def __init__(self, x0, sigma0):
        self.loc = np.asarray(x0, dtype=float)
        sigma0 = np.asarray(sigma0, dtype=float)
        if sigma0.ndim == 0:
            sigma0 = np.repeat(sigma0, self.dim)
        if sigma0.ndim == 1:
            sigma0 = np.diag(sigma0)
        self.scale = sigma0

    @property
    def dim(self):
        return self.loc.size

    def ask(self, num_samples=None, rng=None):
        n = num_samples or (4 + int(3 * np.log(self.dim)))
        n2 = n // 2
        rng = rng or np.random.default_rng()
        z2 = rng.standard_normal((self.dim, n2))
        # orthogonal sampling if possible
        if n2 <= self.dim:
            z2 = qr(z2, mode="economic")[0] * np.sqrt(rng.chisquare(self.dim, n2))
        z = np.hstack([z2, -z2])
        x = self.loc[:, None] + self.scale @ z
        return z, x

    def tell(self, samples, ranking, eps=1e-10):
        # rank samples
        num_samples = samples.shape[1]
        w = np.maximum(0, np.log(num_samples / 2 + 1) - np.log(np.arange(1, num_samples + 1)))
        w = w / np.sum(w) - (1 / num_samples)
        z = samples[:, ranking]
        # estimate gradient
        grad_mu = z @ w
        grad_scale = (z * w) @ z.T
        # update step
        eta_scale = 0.6 * (3 + np.log(self.dim)) / (self.dim * np.sqrt(self.dim))
        loc_step = self.scale @ grad_mu
        self.loc += loc_step
        self.scale = self.scale @ expm(0.5 * eta_scale * grad_scale)
        return norm(self.scale, ord=2) < eps or norm(loc_step, ord=2) < eps or cond(self.scale) * eps > 1
