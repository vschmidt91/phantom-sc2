from bot.parameter.main import BotData
from bot.parameter.normal import NormalParameter

PARAM_MINERAL_WEIGHT = "mineral_weight"
PARAM_VESPENE_WEIGHT = "vespene_weight"

DATA_A_PRIORI = BotData(
    parameters={
        PARAM_MINERAL_WEIGHT: NormalParameter(5.0, 1.0, 1.0),
        PARAM_VESPENE_WEIGHT: NormalParameter(12.0, 1.0, 1.0),
    }
)
