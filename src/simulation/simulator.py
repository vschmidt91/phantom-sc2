
from __future__ import annotations
from functools import cmp_to_key
from typing import TYPE_CHECKING, Iterable, Optional

import numpy as np

from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from .unit import SimulationUnit

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

THREAT_SPECIAL_CASES = {
    UnitTypeId.HIGHTEMPLAR,
    UnitTypeId.ORACLE,
    UnitTypeId.DISRUPTOR,
    UnitTypeId.WIDOWMINE,
    UnitTypeId.RAVEN,
    UnitTypeId.INFESTOR,
    UnitTypeId.INFESTORBURROWED,
    UnitTypeId.SWARMHOSTMP,
    UnitTypeId.SWARMHOSTBURROWEDMP,
    UnitTypeId.VIPER,
    UnitTypeId.LURKER,
}

def is_threat(unit: Unit, target: Unit) -> bool:
    if target.type_id in THREAT_SPECIAL_CASES:
        return True
    elif unit.type_id == UnitTypeId.COLOSSUS:
        return target.can_attack
    elif unit.is_flyer:
        return target.can_attack_air
    else:
        return target.can_attack_ground

ATP_SPECIAL_CASES = {
    UnitTypeId.PHOTONCANNON: 20,
    UnitTypeId.PYLONOVERCHARGED: 20,
    UnitTypeId.BUNKER: 20,
    UnitTypeId.PLANETARYFORTRESS: 20,
    UnitTypeId.AUTOTURRET: 20,
    UnitTypeId.SPINECRAWLER: 20,
    UnitTypeId.SPINECRAWLERUPROOTED: 19,
    UnitTypeId.SPORECRAWLER: 19,
    UnitTypeId.SPORECRAWLERUPROOTED: 19,
    UnitTypeId.MISSILETURRET: 19,
    UnitTypeId.WIDOWMINE: 19,
    UnitTypeId.ORACLESTASISTRAP: 10,
    UnitTypeId.LARVA: 10,
    UnitTypeId.OVERLORDCOCOON: 10,
    UnitTypeId.BROODLORDCOCOON: 10,
    UnitTypeId.BANELINGCOCOON: 10,
    UnitTypeId.RAVAGERCOCOON: 10,
    UnitTypeId.LURKEREGG: 10,
    UnitTypeId.INFESTEDTERRANSEGG: 0,
}

class Simulator(AIComponent):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    def atp(self, unit_type: UnitTypeId) -> int:
        
        if atp := ATP_SPECIAL_CASES.get(unit_type):
            return atp
        elif self.ai.is_structure(unit_type):
            return 11
        else:
            return 20

    def get_attack_target(self, unit: Unit, targets: Iterable[Unit]) -> Optional[Unit]:
        """https://liquipedia.net/starcraft2/Automatic_Targeting"""

        def compare(a: Unit, b: Unit) -> int:

            a_threat = is_threat(unit, a)
            b_threat = is_threat(unit, b)
            if a_threat != b_threat:
                return +1 if a_threat else -1

            a_atp = self.atp(a.type_id)
            b_atp = self.atp(b.type_id)
            if a_atp != b_atp:
                return np.sign(a_atp - b_atp)

            a_distance = unit.distance_to(a)
            b_distance = unit.distance_to(b)
            if a_distance != b_distance:
                return np.sign(b_distance - a_distance)

            return 0

        weapon_range = max(unit.ground_range, unit.air_range)
        scan_range = max(5, weapon_range + 0.5)
        targets_in_range = [t for t in targets if unit.distance_to(t) <= unit.radius + scan_range + t.radius]
        if not any(targets_in_range):
            return None
        
        targets_sorted = sorted(targets_in_range, key=cmp_to_key(compare))
        return targets_sorted[0]