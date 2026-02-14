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
    """Linear transform: y = w · x."""

    coeffs: Sequence[Parameter]

    def transform(self, values: Sequence[float]) -> float:
        return sum(ci.value * vi for ci, vi in zip(self.coeffs, values, strict=True))


@dataclass
class QuadraticTransform:
    """Quadratic transform with optional low-rank approximation.

    Full model (rank is None):
        y = x^T Q x + w · x + b
        where Q is a symmetric matrix stored as upper-triangular entries.
        Param count: n*(n+1)/2 + n + 1

    Low-rank approximation (rank = k):
        y = ||U x||^2 + w · x + b
        where U is a k × n factor matrix, so x^T Q x = x^T (U^T U) x.
        Param count: k*n + n + 1

    Special cases:
        - rank=0: equivalent to linear (ScalarTransform + bias)
        - rank=n with full=False: full-rank but PSD-constrained
        - full=True: unconstrained symmetric Q (not necessarily PSD)
    """

    linear: Sequence[Parameter]
    bias: Parameter
    factors: Sequence[Sequence[Parameter]]  # low-rank: k rows of n
    upper: Sequence[Parameter] | None  # full: n*(n+1)/2, mutually exclusive with factors

    def transform(self, values: Sequence[float]) -> float:
        n = len(self.linear)
        # Linear + bias
        result = sum(wi.value * xi for wi, xi in zip(self.linear, values, strict=True))
        result += self.bias.value
        # Quadratic term
        if self.upper is not None:
            # Full symmetric Q via upper-triangular storage
            idx = 0
            for i in range(n):
                for j in range(i, n):
                    w = self.upper[idx].value
                    result += (1.0 if i == j else 2.0) * w * values[i] * values[j]
                    idx += 1
        else:
            # Low-rank: Q = U^T U, so x^T Q x = sum_k (u_k · x)^2
            for row in self.factors:
                proj = sum(p.value * xi for p, xi in zip(row, values, strict=True))
                result += proj * proj
        return result


@dataclass
class MLPTransform:
    """Single hidden layer MLP: y = v · tanh(W x + b_h) + b_o.

    Param count: hidden_size * (n_inputs + 2) + 1.
    """

    weights: Sequence[Sequence[Parameter]]  # W: hidden_size × n_inputs
    hidden_biases: Sequence[Parameter]  # b_h: hidden_size
    output_weights: Sequence[Parameter]  # v: hidden_size
    output_bias: Parameter  # b_o: scalar

    def transform(self, values: Sequence[float]) -> float:
        hidden = [
            np.tanh(sum(w.value * xi for w, xi in zip(row, values, strict=True)) + b.value)
            for row, b in zip(self.weights, self.hidden_biases, strict=True)
        ]
        result = sum(v.value * h for v, h in zip(self.output_weights, hidden, strict=True))
        result += self.output_bias.value
        return result


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

    def add_quadratic_transform(
        self,
        name: str,
        linear_priors: Sequence[Prior],
        *,
        rank: int = 1,
        full: bool = False,
        bias_prior: Prior = Prior(0.0, 0.1),
        factor_prior: Prior = Prior(0.0, 0.1),
    ) -> QuadraticTransform:
        """Create a quadratic transform.

        Args:
            name: Base name for parameters.
            linear_priors: Priors for linear coefficients (determines n_inputs).
            rank: Rank of the low-rank approximation (ignored if full=True).
            full: If True, use unconstrained symmetric Q (upper-triangular storage).
            bias_prior: Prior for the bias term.
            factor_prior: Prior for quadratic term entries.
        """
        n = len(linear_priors)
        linear = [self.add(f"{name}_l{i}", p) for i, p in enumerate(linear_priors)]
        bias = self.add(f"{name}_b", bias_prior)

        if full:
            upper = [
                self.add(f"{name}_q{i}_{j}", factor_prior)
                for i in range(n)
                for j in range(i, n)
            ]
            return QuadraticTransform(linear, bias, factors=[], upper=upper)
        else:
            factors = [
                [self.add(f"{name}_f{k}_{j}", factor_prior) for j in range(n)]
                for k in range(rank)
            ]
            return QuadraticTransform(linear, bias, factors=factors, upper=None)

    def add_mlp_transform(
        self,
        name: str,
        n_inputs: int,
        hidden_size: int = 3,
        weight_prior: Prior = Prior(0.0, 1.0),
        bias_prior: Prior = Prior(0.0, 0.1),
    ) -> MLPTransform:
        """Create a single-hidden-layer MLP transform.

        Args:
            name: Base name for parameters.
            n_inputs: Number of input features.
            hidden_size: Number of hidden neurons.
            weight_prior: Prior for weight parameters.
            bias_prior: Prior for bias parameters.
        """
        weights = [
            [self.add(f"{name}_w{k}_{j}", weight_prior) for j in range(n_inputs)]
            for k in range(hidden_size)
        ]
        hidden_biases = [self.add(f"{name}_bh{k}", bias_prior) for k in range(hidden_size)]
        output_weights = [self.add(f"{name}_v{k}", weight_prior) for k in range(hidden_size)]
        output_bias = self.add(f"{name}_bo", bias_prior)
        return MLPTransform(weights, hidden_biases, output_weights, output_bias)

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
