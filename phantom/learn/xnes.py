import numpy as np
from scipy.linalg import expm, qr


class XNES:
    def __init__(self, x0, sigma0, seed=None):
        self.loc = np.asarray(x0, dtype=float)
        sigma0 = np.asarray(sigma0, dtype=float)
        if sigma0.ndim == 0:
            sigma0 = np.repeat(sigma0, self.dim)
        if sigma0.ndim == 1:
            sigma0 = np.diag(sigma0)
        self.scale = sigma0
        self.rng = np.random.default_rng(seed)

    @property
    def dim(self):
        return self.loc.size

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
        n_half = num_samples // 2
        z_half = self.rng.standard_normal((self.dim, n_half))
        # orthogonal sampling if possible
        if n_half <= self.dim:
            len_samples = np.sqrt(np.random.chisquare(self.dim, n_half))
            z_basis, _ = qr(z_half, mode="economic")
            z_half = z_basis * len_samples
        z = np.hstack([z_half, -z_half])
        x = self.loc[:, None] + self.scale @ z
        return z, x

    def tell(self, samples, ranking, eta=1.0):
        # rank samples
        num_samples = samples.shape[1]
        w = np.maximum(0, np.log(num_samples / 2 + 1) - np.log(np.arange(1, num_samples + 1)))
        w = w / np.sum(w) - (1 / num_samples)
        z_sorted = samples[:, ranking]
        # estimate gradient
        grad_mu = z_sorted @ w
        grad_scale = (z_sorted * w) @ z_sorted.T
        # update step
        eta_scale = (3 + np.log(self.dim)) / (5 * np.sqrt(self.dim))
        self.loc += eta * (self.scale @ grad_mu)
        self.scale = self.scale @ expm(0.5 * eta * eta_scale * grad_scale)
