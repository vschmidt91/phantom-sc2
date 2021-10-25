
import math

from itertools import chain
from sc2.ids.upgrade_id import UpgradeId
from utils import get_requirements, withEquivalents

from sc2 import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_research_abilities import RESEARCH_INFO

PHI = .5 * (1 + math.sqrt(5))

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
    *withEquivalents(UnitTypeId.WARPPRISM),
    *withEquivalents(UnitTypeId.DRONE),
    # *withEquivalents(UnitTypeId.QUEEN),
    *withEquivalents(UnitTypeId.OVERLORD),
    *withEquivalents(UnitTypeId.BROODLING),
    *withEquivalents(UnitTypeId.OBSERVER),
    *CHANGELINGS
}

TRAINABLE_UNITS = set(u for e in TRAIN_INFO.values() for u in e.keys())
TRAIN_ABILITIES = {
    u: [e[u]["ability"] for e in TRAIN_INFO.values() if u in e]
    for u in TRAINABLE_UNITS
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

REQUIREMENTS = {
    item: set(get_requirements(item))
    for item in chain(UNIT_TRAINED_FROM.keys(), UPGRADE_RESEARCHED_FROM.keys())
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

ROACH_RUSH = [
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.ROACHWARREN,
    UnitTypeId.QUEEN,
    UnitTypeId.OVERLORD,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
]

HATCH17 = [
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.HATCHERY,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    # UnitTypeId.QUEEN,
    # UnitTypeId.QUEEN,
    # UpgradeId.ZERGLINGMOVEMENTSPEED,
    # UnitTypeId.ZERGLING,
    # UnitTypeId.ZERGLING,
]

POOL16 = [
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.HATCHERY,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.QUEEN,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.OVERLORD,
]

POOL12 = [
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.HATCHERY,
    UnitTypeId.QUEEN,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.OVERLORD,
]