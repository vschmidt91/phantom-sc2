
from functools import cmp_to_key
from optparse import Option
from typing import Iterable, Optional
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.position import Point2

import numpy as np

from ..utils import is_structure

PRIORITY_SPECIAL_CASES = {
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

class SimulationWeapon(object):

    def __init__(self, dps: float, range: float) -> None:
        self.dps: float = dps
        self.range: float = range

    @property
    def scan_range(self) -> float:
        return max(5.0, self.range + 0.5)

class SimulationUnit(object):

    def __init__(self, unit: Unit) -> None:

        self.type_id: UnitTypeId = unit.type_id
        self.position: Point2 = unit.position
        self.radius: float = unit.radius
        self.speed: float = unit.movement_speed
        self.health: float = unit.health + unit.shield
        self.ground_weapon: Optional[SimulationWeapon] = None
        self.air_weapon: Optional[SimulationWeapon] = None
        self.is_ground: bool = not unit.is_flying or unit.type_id == UnitTypeId.COLOSSUS
        self.is_air: bool = unit.is_flying
        self.is_structure: bool = is_structure(unit)

        if unit.can_attack_air:
            self.air_weapon = SimulationWeapon(unit.air_dps, unit.air_range)
        if unit.can_attack_ground:
            self.ground_weapon = SimulationWeapon(unit.ground_dps, unit.ground_range)

    @property
    def priority(self) -> int:
        if priority := PRIORITY_SPECIAL_CASES.get(self.type_id):
            return priority
        elif self.is_structure:
            return 11
        else:
            return 20

    def weapon_against(self, unit: 'SimulationUnit') -> Optional[SimulationWeapon]:
        if unit.is_air and self.air_weapon:
            return self.air_weapon
        elif unit.is_ground and self.ground_weapon:
            return self.ground_weapon
        else:
            return None

    def is_threat_to(self, unit: 'SimulationUnit') -> bool:
        if self.type_id in THREAT_SPECIAL_CASES:
            return True
        elif unit.weapon_against(self):
            return True
        else:
            return False

    def weapon_in_range_against(self, unit: 'SimulationUnit') -> Optional[SimulationWeapon]:
        if weapon := self.weapon_against(unit):
            if self.position.distance_to(unit.position) <= self.radius + weapon.range + unit.radius:
                return weapon
            else:
                return None
        else:
            return None


    def select_target(self, units: Iterable['SimulationUnit']) -> Optional['SimulationUnit']:
        """https://liquipedia.net/starcraft2/Automatic_Targeting"""

        def compare(a: SimulationUnit, b: SimulationUnit) -> int:

            a_threat = int(a.is_threat_to(self))
            b_threat = int(b.is_threat_to(self))
            if a_threat != b_threat:
                return  np.sign(a_threat - b_threat)

            a_priority = a.priority
            b_priority = b.priority
            if a.priority != b.priority:
                return np.sign(a_priority - b_priority)

            a_distance = self.position.distance_to(a.position)
            b_distance = self.position.distance_to(b.position)
            if a_distance != b_distance:
                return np.sign(b_distance - a_distance)

            return 0

        unit_weapons = [
            (u, self.weapon_against(u))
            for u in units
        ]
        targets_in_range = [
            u
            for u, w in unit_weapons
            if w and self.position.distance_to(u.position) <= self.radius + w.scan_range + u.radius
        ]
        if not any(targets_in_range):
            return None
        
        targets_sorted = sorted(targets_in_range, key=cmp_to_key(compare))
        return targets_sorted[-1]