from bot.parameter.main import BotData
from bot.parameter.normal import NormalParameter

PARAM_COST_WEIGHTING = "cost_weighting"

PARAM_PRIORS = BotData(
    parameters={
        PARAM_COST_WEIGHTING: NormalParameter(0.0, 1.0, 1.0),
    }
)
