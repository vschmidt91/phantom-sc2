from dataclasses import dataclass

import numpy as np

from phantom.counters.feature_space import CounterFeatureSpace
from phantom.counters.table import CounterExample, examples_to_matrices


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp_values = np.exp(shifted)
    return exp_values / exp_values.sum(axis=1, keepdims=True)


@dataclass(frozen=True)
class TinyMLPCompositionConfig:
    hidden_size: int = 12
    epochs: int = 400
    learning_rate: float = 0.2
    l2: float = 1e-4
    seed: int = 7


@dataclass
class TinyMLPComposition:
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray

    @classmethod
    def from_feature_space(
        cls, feature_space: CounterFeatureSpace, *, hidden_size: int = 12, seed: int = 7
    ) -> "TinyMLPComposition":
        rng = np.random.default_rng(seed)
        feature_dim = feature_space.dimension
        std = np.sqrt(2.0 / max(1, feature_dim))
        w1 = rng.normal(0.0, std, size=(feature_dim, hidden_size))
        b1 = np.zeros(hidden_size, dtype=np.float64)
        w2 = rng.normal(0.0, std, size=(hidden_size, feature_dim))
        b2 = np.zeros(feature_dim, dtype=np.float64)
        return cls(w1=w1, b1=b1, w2=w2, b2=b2)

    @property
    def parameter_count(self) -> int:
        return self.w1.size + self.b1.size + self.w2.size + self.b2.size

    def predict_distribution(self, x: np.ndarray) -> np.ndarray:
        matrix = x.reshape(1, -1) if x.ndim == 1 else x
        hidden_pre = matrix @ self.w1 + self.b1
        hidden = np.maximum(hidden_pre, 0.0)
        logits = hidden @ self.w2 + self.b2
        predictions = _softmax(logits)
        return predictions[0] if x.ndim == 1 else predictions

    def fit(self, x: np.ndarray, y: np.ndarray, *, epochs: int, learning_rate: float, l2: float) -> None:
        sample_count = x.shape[0]
        for _ in range(epochs):
            hidden_pre = x @ self.w1 + self.b1
            hidden = np.maximum(hidden_pre, 0.0)
            logits = hidden @ self.w2 + self.b2
            predictions = _softmax(logits)

            d_logits = (predictions - y) / sample_count
            d_w2 = hidden.T @ d_logits + l2 * self.w2
            d_b2 = d_logits.sum(axis=0)

            d_hidden = d_logits @ self.w2.T
            d_hidden_pre = d_hidden * (hidden_pre > 0.0)
            d_w1 = x.T @ d_hidden_pre + l2 * self.w1
            d_b1 = d_hidden_pre.sum(axis=0)

            self.w2 -= learning_rate * d_w2
            self.b2 -= learning_rate * d_b2
            self.w1 -= learning_rate * d_w1
            self.b1 -= learning_rate * d_b1

    def fit_examples(self, examples: list[CounterExample], *, config: TinyMLPCompositionConfig) -> None:
        x, y = examples_to_matrices(examples)
        self.fit(
            x=x,
            y=y,
            epochs=config.epochs,
            learning_rate=config.learning_rate,
            l2=config.l2,
        )
