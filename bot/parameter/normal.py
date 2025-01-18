import math
from dataclasses import dataclass
from functools import cached_property

from scipy.stats import norm

from river import compose
from river import linear_model
from river import preprocessing

model = compose.Pipeline(
    ('scale', preprocessing.StandardScaler()),
    ('lin_reg', linear_model.LinearRegression())
)

@dataclass(frozen=True)
class NormalParameter:
    """
    >>> NormalParameter(0.0, 1.0, 1.0) + NormalParameter.from_values([0.0])
    NormalParameter(mean=0.0, deviation=1.0, evidence=2.0)
    >>> NormalParameter(0.0, 1.0, 1.0) + NormalParameter.from_values([0.0]) + NormalParameter.from_values([0.0])
    NormalParameter(mean=0.0, deviation=1.0, evidence=3.0)
    >>> NormalParameter.from_values([0.0, 2.0])
    NormalParameter(mean=1.0, deviation=2.0, evidence=2.0)
    >>> NormalParameter.from_values([0.0, 1.0, 2.0])
    NormalParameter(mean=1.0, deviation=2.0, evidence=3.0)
    """

    mean: float
    deviation: float
    evidence: float

    @classmethod
    def from_values(cls, values: list[float]) -> "NormalParameter":
        evidence = float(len(values))
        mean = sum(values) / evidence
        return NormalParameter(
            mean=mean,
            deviation=sum((x - mean) ** 2 for x in values),
            evidence=evidence,
        )

    def __add__(self, other: "NormalParameter") -> "NormalParameter":
        total_evidence = self.evidence + other.evidence
        total_mean = (self.mean * self.evidence + other.mean * other.evidence) / total_evidence
        cross_deviation = (self.evidence * other.evidence / total_evidence) * (other.mean - self.mean) ** 2
        total_deviation = self.deviation + other.deviation + cross_deviation
        return NormalParameter(
            mean=total_mean,
            evidence=total_evidence,
            deviation=total_deviation,
        )

    @cached_property
    def variance(self) -> float:
        return self.deviation / self.evidence

    @cached_property
    def scale(self) -> float:
        return math.sqrt(self.variance)

    @cached_property
    def distribution(self):
        return norm(loc=self.mean, scale=self.scale)
        # return t(df=self.degrees_of_freedom, loc=self.mean, scale=self.scale)
