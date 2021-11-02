
from collections import defaultdict
import math
from itertools import chain

from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS
from sc2.data import Race
from sc2.helpers.devtools import time_this
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_research_abilities import RESEARCH_INFO

from .utils import get_requirements

PHI = .5 * (1 + math.sqrt(5))

WITH_TECH_EQUIVALENTS = {
    unit: { unit } | EQUIVALENTS_FOR_TECH_PROGRESS.get(unit, set())
    for unit in UnitTypeId
}

SUPPLY = {
    Race.Protoss: UnitTypeId.PYLON,
    Race.Terran: UnitTypeId.SUPPLYDEPOT,
    Race.Zerg: UnitTypeId.OVERLORD,
}

TOWNHALL = {
    Race.Protoss: UnitTypeId.NEXUS,
    Race.Terran: UnitTypeId.COMMANDCENTER,
    Race.Zerg: UnitTypeId.HATCHERY,
}

STATIC_DEFENSE = {
    Race.Protoss: { UnitTypeId.PHOTONCANNON },
    Race.Terran: { UnitTypeId.MISSILETURRET },
    Race.Zerg: { UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER },
}

WORKERS = {
    *WITH_TECH_EQUIVALENTS[UnitTypeId.DRONE],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.PROBE],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.SCV],
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
    UnitTypeId.PYLON: 8,
    UnitTypeId.SUPPLYDEPOT: 8,
    UnitTypeId.OVERLORD: 8,
    UnitTypeId.NEXUS: 15,
    UnitTypeId.HATCHERY: 6,
    UnitTypeId.LAIR: 6,
    UnitTypeId.HIVE: 6,
    UnitTypeId.COMMANDCENTER: 15,
    UnitTypeId.COMMANDCENTERFLYING: 15,
    UnitTypeId.ORBITALCOMMAND: 15,
    UnitTypeId.ORBITALCOMMANDFLYING: 15,
    UnitTypeId.PLANETARYFORTRESS: 15,
}

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
}

CIVILIANS = set()
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

TRAIN_ABILITIES = {
    u: {
        e[u]["ability"]
        for e in TRAIN_INFO.values()
        if u in e
    }
    for u in UnitTypeId
}

UNIT_BY_TRAIN_ABILITY = {
    unit_element["ability"] : unit
    for trainer_element in TRAIN_INFO.values()
    for unit, unit_element in trainer_element.items()
}

UPGRADE_BY_RESEARCH_ABILITY = {
    upgrade_element["ability"] : upgrade
    for research_element in RESEARCH_INFO.values()
    for upgrade, upgrade_element in research_element.items()
}

GAS_BY_RACE = {
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