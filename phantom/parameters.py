import lzma
import pickle
from dataclasses import dataclass

from loguru import logger
from river.base.typing import ClfTarget
from river.proba import Multinomial, MultivariateGaussian


@dataclass(frozen=True)
class AgentParameterValues:
    continuous: dict[str, float]
    discrete: dict[str, ClfTarget]


@dataclass(frozen=True)
class AgentParameterDistributions:
    normal: MultivariateGaussian
    multinomial: dict[str, Multinomial]


@dataclass(frozen=True)
class NormalPrior:
    mu: float = 0.0
    sigma: float = 1.0


@dataclass(frozen=True)
class CategoricalPrior:
    categories: list[ClfTarget]


@dataclass
class NormalParameter:
    value: float
    prior: NormalPrior


@dataclass
class CategoricalParameter:
    value: ClfTarget
    prior: CategoricalPrior


class AgentParameters:
    def __init__(self) -> None:
        self.prior_evidence = 32
        self.seed = 32
        self.distributions: AgentParameterDistributions | None = None
        self._continuous = dict[str, NormalParameter]()
        self._discrete = dict[str, CategoricalParameter]()

    def normal(self, name: str, prior: NormalPrior) -> NormalParameter:
        return self._continuous.setdefault(name, NormalParameter(prior.mu, prior))

    def discrete(self, name: str, prior: CategoricalPrior) -> CategoricalParameter:
        return self._discrete.setdefault(name, CategoricalParameter(prior.categories[0], prior))

    def load(self, path: str) -> None:
        logger.info(f"Reading parameters from {path=}")
        with lzma.open(path, "rb") as f:
            self.distributions = pickle.load(f)

    def save(self, path: str) -> None:
        with lzma.open(path, "wb") as f:
            pickle.dump(self.distributions, f)

    def sample(self):
        if not self.distributions:
            self.load_priors()
        for k, v in self.distributions.normal.sample().items():
            self._continuous[k].value = v
        for k, p in self.distributions.multinomial.items():
            self._discrete[k].value = p.sample()

    def load_priors(self) -> None:
        cov = {(i, j): p.prior.sigma if i == j else 0.0 for i, p in self._continuous.items() for j in self._continuous}
        normal = MultivariateGaussian._from_state(
            n=self.prior_evidence,
            mean={k: p.prior.mu for k, p in self._continuous.items()},
            cov=cov,
            ddof=1,
            seed=self.seed,
        )
        multinomial = {k: Multinomial(p.prior.categories, self.seed) for k, p in self._discrete.items()}
        self.distributions = AgentParameterDistributions(
            normal=normal,
            multinomial=multinomial,
        )

    def update_distribution(self) -> None:
        assert self.distributions
        self.distributions.normal.update({k: p.value for k, p in self._continuous.items()})
        for k, p in self._discrete.items():
            self.distributions.multinomial[k].update(p.value)
