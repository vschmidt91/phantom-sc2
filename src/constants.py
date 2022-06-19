
from collections import defaultdict
import math
from itertools import chain
from typing import Dict

from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS, SPEED_INCREASE_DICT, SPEED_UPGRADE_DICT
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_research_abilities import RESEARCH_INFO

from .utils import get_requirements

WITH_TECH_EQUIVALENTS = {
    unit: { unit } | EQUIVALENTS_FOR_TECH_PROGRESS.get(unit, set())
    for unit in UnitTypeId
}

UNIT_TRAINED_FROM_WITH_EQUIVALENTS = {
    item: { 
        equivalent
        for trainer in UNIT_TRAINED_FROM.get(item, [])
        for equivalent in WITH_TECH_EQUIVALENTS[trainer]
    }
    for item in UnitTypeId
}

UPGRADE_RESEARCHED_FROM_WITH_EQUIVALENTS = {
    item: WITH_TECH_EQUIVALENTS.get(UPGRADE_RESEARCHED_FROM.get(item), set())
    for item in UpgradeId
}

ITEM_TRAINED_FROM_WITH_EQUIVALENTS = {
    **UNIT_TRAINED_FROM_WITH_EQUIVALENTS,
    **UPGRADE_RESEARCHED_FROM_WITH_EQUIVALENTS
}

RANGE_UPGRADES: Dict[UnitTypeId, Dict[UpgradeId, int]] = {
    UnitTypeId.COLOSSUS: { UpgradeId.EXTENDEDTHERMALLANCE: 2 },
    UnitTypeId.HYDRALISK: { UpgradeId.EVOLVEGROOVEDSPINES: 1 },
    UnitTypeId.PHOENIX: { UpgradeId.PHOENIXRANGEUPGRADE: 2 },
    UnitTypeId.PLANETARYFORTRESS: { UpgradeId.HISECAUTOTRACKING: 1 },
    UnitTypeId.MISSILETURRET: { UpgradeId.HISECAUTOTRACKING: 1 },
    UnitTypeId.AUTOTURRET: { UpgradeId.HISECAUTOTRACKING: 1 },
}

MACRO_INFO = {
    unit_type: { **TRAIN_INFO.get(unit_type, {}), **RESEARCH_INFO.get(unit_type, {}) }
    for unit_type in set(chain(TRAIN_INFO, RESEARCH_INFO))
}

SPEED_UPGRADES: Dict[UnitTypeId, Dict[UpgradeId, float]] = {
    unit_type: { upgrade: SPEED_INCREASE_DICT[unit_type] }
    for unit_type, upgrade in SPEED_UPGRADE_DICT.items()
    
}

COOLDOWN = {
    AbilityId.EFFECT_CORROSIVEBILE: 7 * 22.4,
    AbilityId.BUILD_CREEPTUMOR_TUMOR: 22 * 22.4,
}

ENERGY_COST = {
    AbilityId.SPAWNCHANGELING_SPAWNCHANGELING: 50.0,
    AbilityId.EFFECT_INJECTLARVA: 25.0,
    AbilityId.BUILD_CREEPTUMOR_QUEEN: 25.0,
    AbilityId.TRANSFUSION_TRANSFUSION: 50.0,
}

WORKERS = {
    *WITH_TECH_EQUIVALENTS[UnitTypeId.DRONE],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.PROBE],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.SCV],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.MULE],
}

LARVA_COST = {
    UnitTypeId.ZERGLING: 0.5,
    UnitTypeId.ROACH: 1.0,
    UnitTypeId.DRONE: 1.0,
    UnitTypeId.OVERLORD: 1.0,
    UnitTypeId.HYDRALISK: 1.0,
    UnitTypeId.INFESTOR: 1.0,
    UnitTypeId.SWARMHOSTMP: 1.0,
    UnitTypeId.ULTRALISK: 1.0,
    UnitTypeId.MUTALISK: 1.0,
    UnitTypeId.CORRUPTOR: 1.0,
    UnitTypeId.VIPER: 1.0,
}

RICH_MINERALS = {
    UnitTypeId.RICHMINERALFIELD,
    UnitTypeId.RICHMINERALFIELD750,
    UnitTypeId.PURIFIERRICHMINERALFIELD,
    UnitTypeId.PURIFIERRICHMINERALFIELD750,
}

RICH_GAS = {
    UnitTypeId.RICHVESPENEGEYSER,
}

TRAINERS = {
    ttt
    for t in UNIT_TRAINED_FROM.values()
    for tt in t
    for ttt in WITH_TECH_EQUIVALENTS[tt]
} | {
    tt
    for t in UPGRADE_RESEARCHED_FROM.values()
    for tt in WITH_TECH_EQUIVALENTS[t]
}

SUPPLY_PROVIDED = {
    Race.Zerg: {
        UnitTypeId.OVERLORD: 8,
        # UnitTypeId.HATCHERY: 6,
        # UnitTypeId.LAIR: 6,
        # UnitTypeId.HIVE: 6,
    },
    Race.Protoss: {
        UnitTypeId.PYLON: 8,
        # UnitTypeId.NEXUS: 15,
    },
    Race.Terran: {
        UnitTypeId.SUPPLYDEPOT: 8,
        # UnitTypeId.COMMANDCENTER: 15,
        # UnitTypeId.COMMANDCENTERFLYING: 15,
        # UnitTypeId.ORBITALCOMMAND: 15,
        # UnitTypeId.ORBITALCOMMANDFLYING: 15,
        # UnitTypeId.PLANETARYFORTRESS: 15,
    }
}

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
}

CIVILIANS = {
    UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.PROBE,
    UnitTypeId.LARVA, UnitTypeId.EGG,
    *WITH_TECH_EQUIVALENTS[UnitTypeId.WARPPRISM],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.DRONE],
    # *WITH_TECH_EQUIVALENTS[UnitTypeId.QUEEN],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.OVERLORD],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.BROODLING],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.OBSERVER],
    *CHANGELINGS
}

UNIT_BY_TRAIN_ABILITY: Dict[AbilityId, UnitTypeId] = {
    unit_element["ability"] : unit
    for trainer_element in TRAIN_INFO.values()
    for unit, unit_element in trainer_element.items()
}

UPGRADE_BY_RESEARCH_ABILITY: Dict[AbilityId, UpgradeId] = {
    upgrade_element["ability"] : upgrade
    for research_element in RESEARCH_INFO.values()
    for upgrade, upgrade_element in research_element.items()
}

ITEM_BY_ABILITY = {
    **UNIT_BY_TRAIN_ABILITY,
    **UPGRADE_BY_RESEARCH_ABILITY
}

GAS_BY_RACE: Dict[Race, UnitTypeId] = {
    Race.Zerg: UnitTypeId.EXTRACTOR,
    Race.Protoss: UnitTypeId.ASSIMILATOR,
    Race.Terran: UnitTypeId.REFINERY,
}

REQUIREMENTS_EXCLUDE = {
    # UnitTypeId.DRONE,
    UnitTypeId.LARVA,
    # UnitTypeId.HATCHERY,
}

REQUIREMENTS_KEYS = {
    *UNIT_TRAINED_FROM.keys(),
    *UPGRADE_RESEARCHED_FROM.keys()
}.difference(REQUIREMENTS_EXCLUDE)

REQUIREMENTS = {
    item: {
        requirement
        for requirement in get_requirements(item)
        if requirement in REQUIREMENTS_KEYS
    }
    for item in REQUIREMENTS_KEYS
}

ZERG_MELEE_UPGRADES = [
    UpgradeId.ZERGMELEEWEAPONSLEVEL1,
    UpgradeId.ZERGMELEEWEAPONSLEVEL2,
    UpgradeId.ZERGMELEEWEAPONSLEVEL3,
]

ZERG_ARMOR_UPGRADES = [
    UpgradeId.ZERGGROUNDARMORSLEVEL1,
    UpgradeId.ZERGGROUNDARMORSLEVEL2,
    UpgradeId.ZERGGROUNDARMORSLEVEL3,
]

ZERG_RANGED_UPGRADES = [
    UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
    UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
    UpgradeId.ZERGMISSILEWEAPONSLEVEL3,
]

ZERG_FLYER_UPGRADES = [
    UpgradeId.ZERGFLYERWEAPONSLEVEL1,
    UpgradeId.ZERGFLYERWEAPONSLEVEL2,
    UpgradeId.ZERGFLYERWEAPONSLEVEL3,
]

ZERG_FLYER_ARMOR_UPGRADES = [
    UpgradeId.ZERGFLYERARMORSLEVEL1,
    UpgradeId.ZERGFLYERARMORSLEVEL2,
    UpgradeId.ZERGFLYERARMORSLEVEL3,
]