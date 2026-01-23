import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np

from phantom.learn.xnes import XNES, ranking_from_comparer


@dataclass(frozen=True)
class Prior:
    mu: float = 0.0
    sigma: float = 1.0


@dataclass
class Parameter:
    name: str
    prior: Prior
    value: float


@dataclass
class ScalarTransform:
    coeffs: Sequence[Parameter]

    def transform(self, values: Sequence[float]) -> float:
        return sum(ci.value * vi for ci, vi in zip(self.coeffs, values, strict=True))


class OptimizationTarget(Enum):
    CostEfficiency = auto()
    MiningEfficiency = auto()
    SupplyEfficiency = auto()


@dataclass(frozen=True)
class OptimizerState:
    names: list[str]
    loc: np.ndarray
    scale: np.ndarray
    batch_z: np.ndarray | None = None  # Genotypes
    batch_x: np.ndarray | None = None  # Phenotypes
    batch_results: list | None = None  # Results collected so far


class ParameterOptimizer:
    def __init__(self, pop_size: int, rng=None):
        self.rng = rng or np.random.default_rng()
        self.pop_size = pop_size + (pop_size % 2)
        self._registry: dict[str, Parameter] = {}

        # Runtime state
        self._xnes: XNES | None = None
        self._current_genotypes: np.ndarray | None = None  # z
        self._current_phenotypes: np.ndarray | None = None  # x
        self._results: list = []

    def add(self, name: str, prior: Prior) -> Parameter:
        if name in self._registry:
            warnings.warn(f"Parameter '{name}' duplicated. Returning existing handle.", stacklevel=2)
            return self._registry[name]

        param = Parameter(name, prior, prior.mu)
        self._registry[name] = param
        return param

    def add_scalar_transform(self, name: str, *priors: Prior) -> ScalarTransform:
        coeffs = [self.add(f"{name}_{i}", p) for i, p in enumerate(priors)]
        return ScalarTransform(coeffs)

    # --- State Management ---

    def _build_initial_state(self) -> tuple[np.ndarray, np.ndarray]:
        """Creates fresh loc/scale from priors."""
        loc = np.array([p.prior.mu for p in self._registry.values()], dtype=float)
        scale_diag = np.array([p.prior.sigma for p in self._registry.values()], dtype=float)
        scale = np.diag(scale_diag)
        return loc, scale

    def load_state(self, state: OptimizerState | None) -> None:
        current_names = list(self._registry.keys())

        # 1. Start with fresh priors
        new_loc, new_scale = self._build_initial_state()

        # 2. Reconcile with saved state
        restored_batch_z = None
        restored_batch_x = None
        restored_results = []

        if state is not None:
            # Map old indices to new indices
            old_name_to_idx = {n: i for i, n in enumerate(state.names)}
            curr_indices = []
            old_indices = []

            for i, name in enumerate(current_names):
                if name in old_name_to_idx:
                    curr_indices.append(i)
                    old_indices.append(old_name_to_idx[name])

            if curr_indices:
                new_loc[curr_indices] = state.loc[old_indices]
                ix_curr = np.ix_(curr_indices, curr_indices)
                ix_old = np.ix_(old_indices, old_indices)
                new_scale[ix_curr] = state.scale[ix_old]

            if state.batch_z is not None and state.batch_x is not None:
                n_samples = state.batch_z.shape[1]
                n_params = len(current_names)

                # Create new arrays filled with "Neutral" values
                # z=0 (Mean), x=mu (Prior Mean)
                new_z = np.zeros((n_params, n_samples))
                new_x = np.tile(new_loc[:, None], (1, n_samples))

                # Copy data for matching parameters
                if curr_indices:
                    # Copy rows where names match
                    new_z[curr_indices, :] = state.batch_z[old_indices, :]
                    new_x[curr_indices, :] = state.batch_x[old_indices, :]

                restored_batch_z = new_z
                restored_batch_x = new_x
                restored_results = list(state.batch_results) if state.batch_results else []

        # 3. Initialize XNES
        self._xnes = XNES(new_loc, new_scale)

        # 4. Restore or Reset Batch
        if restored_batch_z is not None:
            self._current_genotypes = restored_batch_z
            self._current_phenotypes = restored_batch_x
            self._results = restored_results
        else:
            self._reset_batch()

    def get_state(self) -> OptimizerState:
        if self._xnes is None:
            self.load_state(None)
        assert self._xnes is not None
        return OptimizerState(
            names=list(self._registry.keys()),
            loc=self._xnes.loc,
            scale=self._xnes.scale,
            batch_z=self._current_genotypes,
            batch_x=self._current_phenotypes,
            batch_results=list(self._results),
        )

    # --- Optimization Loop ---

    def _reset_batch(self):
        """Generates new population."""
        if self._xnes is None:
            self.load_state(None)

        # Use XNES to generate samples
        self._current_genotypes, self._current_phenotypes = self._xnes.ask(self.pop_size, self.rng)
        self._results = []

    def set_values_from_best(self) -> None:
        """Sets all parameters to the current best estimate (mean)."""
        if self._xnes is None:
            self.load_state(None)
        assert self._xnes is not None
        for i, param in enumerate(self._registry.values()):
            param.value = self._xnes.loc[i]

    def set_values_from_sample(self, sample_index: int) -> None:
        """Sets parameters to the specific individual in the population."""
        if self._current_phenotypes is None:
            self._reset_batch()

        # Ensure index wraps if we request more samples than pop_size (for safety)
        assert self._current_phenotypes is not None
        idx = sample_index % self._current_phenotypes.shape[1]

        for i, param in enumerate(self._registry.values()):
            param.value = self._current_phenotypes[i, idx]

    def set_values_from_latest(self):
        return self.set_values_from_sample(len(self._results))

    def tell_result(self, result, compare_fn=None) -> bool:
        """
        Returns True if batch is complete and update happened.
        """
        assert self._xnes is not None
        self._results.append(result)

        compare_fn = compare_fn or (lambda a, b: a - b)

        if len(self._results) >= self.pop_size:
            # 1. Rank
            ranking = ranking_from_comparer(self._results, compare_fn)

            # 2. Update Optimizer
            self._xnes.tell(self._current_genotypes, ranking)

            # 3. Prepare next batch
            self._reset_batch()
            return True
        return False


class ParameterManager:
    def __init__(self, pop_size: int, rng=None):
        self.optimize = {t: ParameterOptimizer(pop_size, rng) for t in OptimizationTarget}

    def save(self) -> dict[str, OptimizerState]:
        return {t.name: opt.get_state() for t, opt in self.optimize.items()}

    def load(self, data: dict[str, OptimizerState]) -> None:
        for t, opt in self.optimize.items():
            state = data.get(t.name)
            opt.load_state(state)

    def tell(self, results: Mapping[OptimizationTarget, float]) -> None:
        for t, opt in self.optimize.items():
            result = results[t]
            opt.tell_result(result)
