import numpy as np
from numpy.linalg import cond, norm
from scipy.linalg import expm, qr
from scipy.stats import chi


class XCMA:
    def __init__(self, x0, sigma0, pc=None, ps=None):
        self.d = len(x0)
        self.loc = np.array(x0, float)
        scale = np.asarray(sigma0, dtype=float)
        if scale.ndim == 0:
            scale = np.repeat(scale, self.d)
        if scale.ndim == 1:
            scale = np.diag(scale)
        self.scale = scale
        self.sigma = 1.0
        self.pc = pc or np.zeros(self.d)
        self.ps = ps or np.zeros(self.d)

    def ask(self, num_samples=None, rng=None):
        n = num_samples or (4 + int(3 * np.log(self.d)))
        rng = rng or np.random.default_rng()
        n2 = n // 2
        z2 = rng.standard_normal((self.d, n2))
        if z2.shape[1] <= z2.shape[0]:
            z2 = qr(z2, mode="economic")[0] * np.sqrt(rng.chisquare(self.d, n2))
        z = np.hstack([z2, -z2])
        x = self.loc[:, None] + self.sigma * (self.scale @ z)
        return z, x

    def tell(self, samples, ranking, epsilon=1e-10):
        n = samples.shape[1]
        w = np.maximum(0, np.log(n / 2 + 1) - np.log(np.arange(1, n + 1)))
        w = w / np.sum(w) - 1 / n
        mueff = (norm(w, 1) / norm(w, 2)) ** 2
        cc = (4 + mueff / self.d) / (self.d + 4 + 2 * mueff / self.d)
        cs = (mueff + 2) / (self.d + mueff + 5)
        c1 = 2 / ((self.d + 1.3) ** 2 + mueff)
        cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((self.d + 2) ** 2 + mueff))
        ds = 1 + cs + 2 * max(0, np.sqrt((mueff - 1) / (self.d + 1)) - 1)
        z = samples[:, ranking]
        grad_mu = z @ w
        grad_scale = (z * w) @ z.T
        self.ps = (1 - cs) * self.ps + np.sqrt(cs * (2 - cs) * mueff) * grad_mu
        hs = 1 if norm(self.ps) < 1.4 + 2 / (self.d + 1) else 0
        self.pc = (1 - cc) * self.pc + hs * np.sqrt(cc * (2 - cc) * mueff) * grad_mu
        step_scale = c1 * (np.outer(self.pc, self.pc) - np.eye(self.d)) + cmu * grad_scale
        self.scale = self.scale @ expm(0.5 * step_scale)
        self.sigma *= np.exp(cs / ds * (norm(self.ps) / chi.mean(self.d) - 1))
        step_loc = self.sigma * (self.scale @ grad_mu)
        self.loc += step_loc
        return bool(
            self.sigma < epsilon
            or norm(self.scale, ord=2) < epsilon
            or norm(step_loc, ord=2) < epsilon
            or cond(self.scale) > 1 / epsilon
        )
