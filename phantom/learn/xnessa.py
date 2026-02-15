from functools import cmp_to_key

import numpy as np
from scipy.linalg import expm, qr


def ranking_from_comparer(population, compare_func, maximize=True):
    def idx_compare(i, j):
        return compare_func(population[i], population[j])

    indices = sorted(range(len(population)), key=cmp_to_key(idx_compare), reverse=maximize)
    return indices


class XNESSA:
    def __init__(self, x0, sigma0):
        self.loc = np.asarray(x0, dtype=float)
        sigma0 = np.asarray(sigma0, dtype=float)
        if sigma0.ndim == 0:
            sigma0 = np.repeat(sigma0, self.dim)
        if sigma0.ndim == 1:
            sigma0 = np.diag(sigma0)
        self.sigma = np.sqrt(np.linalg.det(sigma0) ** (1.0 / self.dim))
        self.B = sigma0 / self.sigma
        self.p_sigma = np.zeros(self.dim)

    @property
    def dim(self):
        return self.loc.size

    @property
    def scale(self):
        return self.sigma * self.B

    def ask(self, num_samples=None, rng=None):
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

    def tell(self, samples, ranking, eta=1.0):
        num_samples = samples.shape[1]

        # 1. Weights Calculation
        # Raw weights (log-normal)
        w_raw = np.maximum(0, np.log(num_samples / 2 + 1) - np.log(np.arange(1, num_samples + 1)))

        # A. Positive-Only Weights (For CSA Step-Size) [Standard CMA]
        w_pos = w_raw / np.sum(w_raw)
        mu_eff_pos = 1.0 / np.sum(w_pos**2)

        # B. Active Weights (For Mean & Covariance) [xNES/Active-CMA]
        # Sum to 0
        w_active = w_pos - (1.0 / num_samples)

        # 2. Extract Sorted Samples
        z_sorted = samples[:, ranking]

        # 3. Calculate Gradients
        # Gradient for Mean/Covariance (uses Active Weights)
        z_sorted @ w_active

        # Gradient for Step-Size Path (uses Positive Weights ONLY)
        # This prevents "repulsion" from bad samples from inflating the path length
        grad_mu_pos = z_sorted @ w_pos

        # Trace-free Gradient for B (Shape)
        grad_B = (z_sorted * w_active) @ z_sorted.T
        grad_B_trace = np.trace(grad_B) / self.dim
        grad_B_shape = grad_B - grad_B_trace * np.eye(self.dim)

        # 4. CSA Step Size Update (Using Positive Stats)
        c_sigma = (mu_eff_pos + 2) / (self.dim + mu_eff_pos + 5)
        d_sigma = 1 + 2 * max(0, np.sqrt((mu_eff_pos - 1) / (self.dim + 1)) - 1) + c_sigma

        expected_norm = np.sqrt(self.dim) * (1 - 1 / (4 * self.dim) + 1 / (21 * self.dim**2))

        # Update Path using Positive Gradient
        self.p_sigma = (1 - c_sigma) * self.p_sigma + np.sqrt(c_sigma * (2 - c_sigma) * mu_eff_pos) * grad_mu_pos

        # Standard CSA Update with Clipping (Safety)
        sigma_log_step = (c_sigma / d_sigma) * (np.linalg.norm(self.p_sigma) / expected_norm - 1)
        sigma_update = np.exp(np.clip(sigma_log_step, -0.5, 0.5))  # Clip to prevent instant explosion

        # 5. Parameter Updates
        eta_B = (3 + np.log(self.dim)) / (5 * np.sqrt(self.dim))

        # Mean moves by Active Gradient
        self.loc += eta * self.sigma * (self.B @ grad_mu_pos)

        # B moves by Active Gradient (Shape only)
        self.B = self.B @ expm(0.5 * eta * eta_B * grad_B_shape)

        # Sigma update
        self.sigma *= sigma_update
