import numpy as np
from scipy.linalg import expm


class XCMA:
    def __init__(self, x0, sigma0, lam=None):
        self.d = len(x0)
        self.m = np.array(x0, float)
        self.sig = sigma0
        self.lam = lam or (4 + int(3 * np.log(self.d)))
        self.mu = self.lam // 2
        self.w = np.log(self.mu + 0.5) - np.log(np.arange(1, self.mu + 1))
        self.w /= self.w.sum()
        self.mueff = 1 / (self.w**2).sum()

        self.cc = (4 + self.mueff / self.d) / (self.d + 4 + 2 * self.mueff / self.d)
        self.cs = (self.mueff + 2) / (self.d + self.mueff + 5)
        self.c1 = 2 / ((self.d + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1, 2 * (self.mueff - 2 + 1 / self.mueff) / ((self.d + 2) ** 2 + self.mueff))
        self.ds = 1 + self.cs + 2 * max(0, np.sqrt((self.mueff - 1) / (self.d + 1)) - 1) + self.cs

        self.A = np.eye(self.d)
        self.pc = np.zeros(self.d)
        self.ps = np.zeros(self.d)
        self.gen = 0

    def ask(self, rng=None):
        rng = rng or np.random.default_rng()
        self.z = rng.standard_normal((self.d, self.lam))
        return self.m[:, None] + self.sig * (self.A @ self.z)

    def tell(self, fitnesses):
        idx = np.argsort(fitnesses)[: self.mu]
        z_sel = self.z[:, idx]
        z_w = z_sel @ self.w

        self.m += self.sig * (self.A @ z_w)
        self.ps = (1 - self.cs) * self.ps + np.sqrt(self.cs * (2 - self.cs) * self.mueff) * z_w

        hs = (
            1
            if np.linalg.norm(self.ps) / np.sqrt(1 - (1 - self.cs) ** (2 * (self.gen + 1))) < 1.4 + 2 / (self.d + 1)
            else 0
        )
        self.pc = (1 - self.cc) * self.pc + hs * np.sqrt(self.cc * (2 - self.cc) * self.mueff) * z_w

        G = self.c1 * (np.outer(self.pc, self.pc) - np.eye(self.d)) + self.cmu * (
            (z_sel * self.w) @ z_sel.T - np.eye(self.d)
        )

        self.A = self.A @ expm(0.5 * G)
        self.sig *= np.exp(self.cs / self.ds * (np.linalg.norm(self.ps) / np.sqrt(self.d) - 1))
        self.gen += 1
