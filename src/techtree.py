

from enum import Enum, Flag, auto
import json
from dataclasses import dataclass
from typing import List, Set, Union, Optional, Dict
from functools import cached_property

from sc2.data import Race, Attribute

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from src.constants import LARVA_COST

from .cost import Cost

class TechTreeAbilityTarget(Flag):
    Point = auto()
    Unit = auto()
    PointOrUnit = Point | Unit

@dataclass
class TechTreeAbilityTargetResearch:
    upgrade: UpgradeId

class TechTreeAbilityTargetUnitType(Enum):
    Build = auto()
    BuildOnUnit = auto()
    BuildInstant = auto()
    Train = auto()
    TrainPlace = auto()
    Morph = auto()
    MorphPlace = auto()

@dataclass
class TechTreeAbilityTargetUnit:
    type: TechTreeAbilityTargetUnitType
    unit: UnitTypeId

@dataclass
class TechTreeAbility:
    id: AbilityId
    name: str
    cast_range: float
    energy_cost: int
    allow_minimap: bool
    allow_autocast: bool
    effect: List
    buff: List
    cooldown: int
    target: Union[TechTreeAbilityTarget, TechTreeAbilityTargetResearch, TechTreeAbilityTargetUnit]

@dataclass
class TechTreeWeaponBonus:
    against: Attribute
    damage: float

class TechTreeWeaponType(Flag):
    Ground = auto()
    Air = auto()
    Any = Ground | Air

@dataclass
class TechTreeWeapon:
    target_type: TechTreeWeaponType
    damage_per_hit: float
    damage_splash: int
    attacks: int
    range: float
    cooldown: float
    bonuses: List[TechTreeWeaponBonus]

@dataclass
class TechTreeUnit:
    id: UnitTypeId
    name: str
    race: Race
    supply: float
    max_health: float
    armor: float
    sight: float
    speed_creep_mul: float
    weapons: List[TechTreeWeapon]
    attributes: List[Attribute]
    abilities: Set[AbilityId]
    size: int
    accepts_addon: bool
    needs_power: bool
    needs_creep: bool
    needs_geyser: bool
    is_structure: bool
    is_addon: bool
    is_worker: bool
    is_townhall: bool
    minerals: int
    gas: int
    time: float
    is_flying: bool
    radius: Optional[float] = None
    cargo_size: Optional[int] = None
    speed: Optional[float] = None
    max_shield: Optional[float] = None
    max_energy: Optional[float] = None
    start_energy: Optional[float] = None
    normal_mode: Optional[int] = None
    cargo_capacity: Optional[int] = None
    detection_range: Optional[float] = None
    power_radius: Optional[float] = None

    @cached_property
    def can_attack_ground(self) -> bool:
        if self.id in { UnitTypeId.BATTLECRUISER, UnitTypeId.ORACLE }:
            return True
        return any(weapon.target_type & TechTreeWeaponType.Ground for weapon in self.weapons)

    @cached_property
    def can_attack_air(self) -> bool:
        if self.id in { UnitTypeId.BATTLECRUISER }:
            return True
        return any(weapon.target_type & TechTreeWeaponType.Air for weapon in self.weapons)

    @cached_property
    def cost(self) -> Cost:
        return Cost(self.minerals, self.gas, self.supply, LARVA_COST.get(self.id, 0))

@dataclass
class TechTreeCost:
    minerals: int
    gas: int
    time: float

@dataclass
class TechTreeUpgrade:
    id: UpgradeId
    name: str
    cost: TechTreeCost

    @cached_property
    def cost2(self) -> Cost:
        return Cost(self.cost.minerals, self.cost.gas, 0, 0)

class TechTree:

    def __init__(self, path: str) -> None:
        with open(path) as file:
            data = json.load(file)

        self.abilities: Dict[AbilityId, TechTreeAbility] = dict()
        for item in data['Ability']:

            item['id'] = AbilityId(item['id'])

            if isinstance(item['target'], dict):
                [(key, value)] = item['target'].items()
                if key =='Research':
                    item['target'] = TechTreeAbilityTargetResearch(UpgradeId(value['upgrade']))
                else:
                    item['target'] = TechTreeAbilityTargetUnit(TechTreeAbilityTargetUnitType[key], UnitTypeId(value['produces']))
            elif item['target'] == 'None':
                item['target'] = TechTreeAbilityTarget(0)
            else:
                item['target'] = TechTreeAbilityTarget[item['target']]

            ability = TechTreeAbility(**item)
            self.abilities[ability.id] = ability

        self.units: Dict[UnitTypeId, TechTreeUnit] = dict()
        for item in data['Unit']:

            item['id'] = UnitTypeId(item['id'])
            item['race'] = Race[item['race']]
            item['attributes'] = [Attribute[a] for a in item['attributes']]
            item['abilities'] = {AbilityId(a['ability']) for a in item['abilities']}

            weapons = []
            for weapon in item['weapons']:
                weapon['target_type'] = TechTreeWeaponType[weapon['target_type']]
                bonuses = []
                for bonus in weapon['bonuses']:
                    bonus['against'] = Attribute[bonus['against']]
                    bonuses.append(TechTreeWeaponBonus(**bonus))
                weapon['bonuses'] = bonuses
                weapons.append(TechTreeWeapon(**weapon))
            item['weapons'] = weapons
                
            unit = TechTreeUnit(**item)
            self.units[unit.id] = unit
            
        self.upgrades: Dict[UpgradeId, TechTreeUpgrade] = dict() 
        for item in data['Upgrade']:

            item['id'] = UpgradeId(item['id'])

            item['cost'] = TechTreeCost(**item['cost'])

            upgrade = TechTreeUpgrade(**item)
            self.upgrades[upgrade.id] = upgrade