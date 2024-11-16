import numpy as np
from sc2.constants import WORKER_TYPES
from sc2.ids.unit_typeid import UnitTypeId

from bot.common.unit_composition import UnitComposition

COMPOSTION_FILTER: list[UnitTypeId] = [
    *WORKER_TYPES,
    UnitTypeId.DRONE,
    UnitTypeId.DRONEBURROWED,
    UnitTypeId.SCV,
    UnitTypeId.PROBE,
    UnitTypeId.HATCHERY,
    UnitTypeId.LAIR,
    UnitTypeId.HIVE,
    UnitTypeId.COMMANDCENTER,
    UnitTypeId.COMMANDCENTERFLYING,
    UnitTypeId.ORBITALCOMMAND,
    UnitTypeId.ORBITALCOMMANDFLYING,
    UnitTypeId.PLANETARYFORTRESS,
    UnitTypeId.NEXUS,
]


def unit_composition_to_vector(c: UnitComposition) -> np.ndarray:
    return np.array([c[k] for k in COMPOSTION_FILTER])


def vector_to_unit_composition(s: np.ndarray) -> UnitComposition:
    return UnitComposition({k: s[i] for i, k in enumerate(COMPOSTION_FILTER)})
