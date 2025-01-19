from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterPrior:
    mean: float
    variance: float


PARAM_COST_WEIGHTING = "cost_weighting"

PARAMETER_NAMES = [
    PARAM_COST_WEIGHTING,
]

PARAM_PRIORS = {
    PARAM_COST_WEIGHTING: ParameterPrior(0, 1),
}
