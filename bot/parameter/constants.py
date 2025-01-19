from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterPrior:
    mean: float
    variance: float


PARAM_DUMMY = "dummy"
PARAM_COST_WEIGHTING = "cost_weighting"

PARAM_PRIORS = {
    PARAM_DUMMY: ParameterPrior(0, 1),
    PARAM_COST_WEIGHTING: ParameterPrior(0, 1),
}
