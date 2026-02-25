from functools import cmp_to_key

import numpy as np
from numpy.linalg import cond, norm
from scipy.linalg import expm, qr


def ranking_from_comparer(population, compare_func, maximize=True):
    def idx_compare(i, j):
        return compare_func(population[i], population[j])

    indices = sorted(range(len(population)), key=cmp_to_key(idx_compare), reverse=maximize)
    return indices


class XNESSA:
    def __init__(self, x0, sigma0):
        self.loc = np.asarray(x0, dtype=float)
        if self.dim == 0:
            self.sigma = 1.0
            self.B = np.eye(0)
            self.p_sigma = np.zeros(0)
            return
        scale0 = np.asarray(sigma0, dtype=float)
        if scale0.ndim == 0:
            scale0 = np.repeat(scale0, self.dim)
        if scale0.ndim == 1:
            scale0 = np.diag(scale0)
        sign, logdet = np.linalg.slogdet(scale0)
        self.sigma = max(float(np.exp(logdet / self.dim) if sign > 0 else 1.0), 1e-12)
        self.B = scale0 / self.sigma
        self.p_sigma = np.zeros(self.dim)

    @property
    def dim(self):
        return self.loc.size

    @property
    def scale(self):
        return self.sigma * self.B

    def ask(self, num_samples=None, rng=None):
        if self.dim == 0:
            n = int(num_samples) if num_samples is not None else 4
            return np.zeros((0, n)), np.zeros((0, n))

        n = num_samples or (4 + int(3 * np.log(self.dim)))
        n_half = n // 2
        rng = rng or np.random.default_rng()

        z_half = np.empty((self.dim, n_half))
        for start in range(0, n_half, self.dim):
            end = min(start + self.dim, n_half)
            k = end - start
            raw = rng.standard_normal((self.dim, k))
            lengths = np.sqrt(rng.chisquare(self.dim, k))
            basis, _ = qr(raw, mode="economic")
            z_half[:, start:end] = basis * lengths

        z = np.hstack([z_half, -z_half])
        x = self.loc[:, None] + self.scale @ z
        return z, x

    def tell(self, samples, ranking, eps=1e-10):
        if self.dim == 0:
            return True

        n = samples.shape[1]
        d = self.dim

        w_pos = np.maximum(0, np.log(n / 2 + 1) - np.log(np.arange(1, n + 1)))
        w_pos /= np.sum(w_pos)
        mu_eff_pos = 1.0 / np.sum(w_pos**2)
        w_active = w_pos - (1.0 / n)
        z_sorted = samples[:, ranking]

        grad_mu = z_sorted @ w_active
        grad_mu_pos = z_sorted @ w_pos
        grad_B = (z_sorted * w_active) @ z_sorted.T
        grad_B_shape = grad_B - (np.trace(grad_B) / d) * np.eye(d)

        c_sigma = (mu_eff_pos + 2.0) / (d + mu_eff_pos + 5.0)
        d_sigma = 1.0 + 2.0 * max(0.0, np.sqrt((mu_eff_pos - 1.0) / (d + 1.0)) - 1.0) + c_sigma
        expected_norm = np.sqrt(d) * (1.0 - 1.0 / (4.0 * d) + 1.0 / (21.0 * d * d))
        self.p_sigma = (1 - c_sigma) * self.p_sigma + np.sqrt(c_sigma * (2 - c_sigma) * mu_eff_pos) * grad_mu_pos
        self.sigma *= float(
            np.exp(np.clip((c_sigma / d_sigma) * (np.linalg.norm(self.p_sigma) / expected_norm - 1), -0.5, 0.5))
        )

        eta_B = 0.6 * (3.0 + np.log(d)) / (d * np.sqrt(d))
        loc_step = self.sigma * (self.B @ grad_mu)

        self.loc += loc_step
        self.B = self.B @ expm(0.5 * eta_B * grad_B_shape)

        sign, logdet = np.linalg.slogdet(self.B)
        if sign > 0:
            self.B *= np.exp(-logdet / d)

        scale = self.scale
        return self.sigma < eps or norm(scale, 2) < eps or norm(loc_step, 2) < eps or cond(scale) * eps > 1
