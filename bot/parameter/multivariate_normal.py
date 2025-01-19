import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from scipy.stats import norm, multivariate_normal


def square_vector(v: np.ndarray) -> np.ndarray:
    """
    Square a vector.
    >>> square_vector(np.array([1., 2.]))
    np.array([[1., 2.], [2., 4.]])
    """
    return v.reshape((-1, 1)) @ v.reshape((1, -1))


@dataclass(frozen=True)
class NormalParameters:

    mean: np.ndarray
    deviation: np.ndarray
    evidence: float

    @classmethod
    def from_values(cls, values: list[np.ndarray]) -> "NormalParameters":
        evidence = float(len(values))
        mean = sum(values) / evidence
        return NormalParameters(
            mean=mean,
            deviation=sum(square_vector(x - mean) for x in values),
            evidence=evidence,
        )

    def __add__(self, other: "NormalParameters") -> "NormalParameters":
        total_evidence = self.evidence + other.evidence
        total_mean = (self.mean * self.evidence + other.mean * other.evidence) / total_evidence
        cross_deviation = (self.evidence * other.evidence / total_evidence) * square_vector(other.mean - self.mean)
        total_deviation = self.deviation + other.deviation + cross_deviation
        return NormalParameters(
            mean=total_mean,
            evidence=total_evidence,
            deviation=total_deviation,
        )

    @cached_property
    def covariance(self) -> np.ndarray:
        return self.deviation / self.evidence

    @cached_property
    def distribution(self):
        return multivariate_normal(mean=self.mean, cov=self.covariance)

    def to_dict(self):
        return {
            "mean": self.mean.tolist(),
            "deviation": self.deviation.tolist(),
            "evidence": self.evidence,
        }
