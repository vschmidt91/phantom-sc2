
from collections import defaultdict
import math
from itertools import chain
from typing import Dict

from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS
from sc2.data import Race
from sc2.helpers.devtools import time_this
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_research_abilities import RESEARCH_INFO

from .utils import get_requirements

PHI = .5 * (1 + math.sqrt(5))

BUILD_ORDER_PRIORITY = 10

WITH_TECH_EQUIVALENTS = {
    unit: { unit } | EQUIVALENTS_FOR_TECH_PROGRESS.get(unit, set())
    for unit in UnitTypeId
}

SUPPLY = {
    Race.Protoss: UnitTypeId.PYLON,
    Race.Terran: UnitTypeId.SUPPLYDEPOT,
    Race.Zerg: UnitTypeId.OVERLORD,
}

TOWNHALL_ABILITY_BY_RACE: Dict[Race, AbilityId] = {
    Race.Protoss: AbilityId.PROTOSSBUILD_NEXUS,
    Race.Terran: AbilityId.TERRANBUILD_COMMANDCENTER,
    Race.Zerg: AbilityId.ZERGBUILD_HATCHERY,
}

RANGE_UPGRADES: Dict[UnitTypeId, Dict[UpgradeId, int]] = {
    UnitTypeId.COLOSSUS: { UpgradeId.EXTENDEDTHERMALLANCE: 2 },
    UnitTypeId.HYDRALISK: { UpgradeId.EVOLVEGROOVEDSPINES: 1 },
    UnitTypeId.PHOENIX: { UpgradeId.PHOENIXRANGEUPGRADE: 2 },
    UnitTypeId.PLANETARYFORTRESS: { UpgradeId.HISECAUTOTRACKING: 1 },
    UnitTypeId.MISSILETURRET: { UpgradeId.HISECAUTOTRACKING: 1 },
    UnitTypeId.AUTOTURRET: { UpgradeId.HISECAUTOTRACKING: 1 },
}

CREEP_ABILITIES = {
    UnitTypeId.QUEEN: AbilityId.BUILD_CREEPTUMOR_QUEEN,
    UnitTypeId.CREEPTUMORBURROWED: AbilityId.BUILD_CREEPTUMOR_TUMOR,
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
    # *WITH_TECH_EQUIVALENTS[UnitTypeId.OVERLORD],
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

UNIT_HP = {

    UnitTypeId.ADEPT: 0,
    UnitTypeId.ARCHON: 0,
    UnitTypeId.CARRIER: 0,
    UnitTypeId.COLOSSUS: 0,
    UnitTypeId.DARKTEMPLAR: 0,
    UnitTypeId.DISRUPTOR: 0,
    UnitTypeId.HIGHTEMPLAR: 0,
    UnitTypeId.IMMORTAL: 0,
    UnitTypeId.MOTHERSHIP: 0,
    UnitTypeId.OBSERVER: 0,
    UnitTypeId.ORACLE: 0,
    UnitTypeId.PHOENIX: 0,
    UnitTypeId.PROBE: 0,
    UnitTypeId.SENTRY: 0,
    UnitTypeId.STALKER: 0,
    UnitTypeId.VOIDRAY: 0,
    UnitTypeId.WARPPRISM: 0,
    UnitTypeId.ZEALOT: 0,

    UnitTypeId.ASSIMILATOR: 0,
    UnitTypeId.CYBERNETICSCORE: 0,
    UnitTypeId.DARKSHRINE: 0,
    UnitTypeId.FLEETBEACON: 0,
    UnitTypeId.FORGE: 0,
    UnitTypeId.GATEWAY: 0,
    UnitTypeId.NEXUS: 0,
    UnitTypeId.PHOTONCANNON: 0,
    UnitTypeId.PYLON: 0,
    UnitTypeId.ROBOTICSFACILITY: 0,
    UnitTypeId.ROBOTICSBAY: 0,
    UnitTypeId.SHIELDBATTERY: 0,
    UnitTypeId.STARGATE: 0,
    UnitTypeId.TEMPLARARCHIVE: 0,
    UnitTypeId.TWILIGHTCOUNCIL: 0,
    UnitTypeId.WARPGATE: 0,

    UnitTypeId.BANSHEE: 0,
    UnitTypeId.BATTLECRUISER: 0,
    UnitTypeId.CYCLONE: 0,
    UnitTypeId.GHOST: 0,
    UnitTypeId.HELLION: 0,
    UnitTypeId.LIBERATOR: 0,
    UnitTypeId.MARAUDER: 0,
    UnitTypeId.MARINE: 0,
    UnitTypeId.MEDIVAC: 0,
    UnitTypeId.MULE: 0,
    UnitTypeId.RAVEN: 0,
    UnitTypeId.REAPER: 0,
    UnitTypeId.SCV: 0,
    UnitTypeId.SIEGETANK: 0,
    UnitTypeId.THOR: 0,
    UnitTypeId.VIKING: 0,
    UnitTypeId.AUTOTURRET: 0,
    UnitTypeId.POINTDEFENSEDRONE: 0,
    UnitTypeId.WIDOWMINE: 0,

    UnitTypeId.ARMORY: 0,
    UnitTypeId.BARRACKS: 0,
    UnitTypeId.BUNKER: 0,
    UnitTypeId.COMMANDCENTER: 0,
    UnitTypeId.ORBITALCOMMAND: 0,
    UnitTypeId.PLANETARYFORTRESS: 0,
    UnitTypeId.ENGINEERINGBAY: 0,
    UnitTypeId.FACTORY: 0,
    UnitTypeId.FUSIONCORE: 0,
    UnitTypeId.GHOSTACADEMY: 0,
    UnitTypeId.MISSILETURRET: 0,
    UnitTypeId.REACTOR: 0,
    UnitTypeId.REFINERY: 0,
    UnitTypeId.SENSORTOWER: 0,
    UnitTypeId.STARPORT: 0,
    UnitTypeId.SUPPLYDEPOT: 0,
    UnitTypeId.TECHLAB: 0,

    UnitTypeId.BROODLORD: 0,
    UnitTypeId.CORRUPTOR: 0,
    UnitTypeId.DRONE: 0,
    UnitTypeId.HYDRALISK: 0,
    UnitTypeId.INFESTOR: 0,
    UnitTypeId.LARVA: 0,
    UnitTypeId.MUTALISK: 0,
    UnitTypeId.OVERLORD: 0,
    UnitTypeId.OVERSEER: 0,
    UnitTypeId.QUEEN: 0,
    UnitTypeId.ROACH: 0,
    UnitTypeId.ULTRALISK: 0,
    UnitTypeId.ZERGLING: 0,
    UnitTypeId.BANELING: 0,
    UnitTypeId.BROODLING: 0,
    UnitTypeId.CHANGELING: 0,

    UnitTypeId.BANELINGNEST: 0,
    UnitTypeId.CREEPTUMOR: 0,
    UnitTypeId.EVOLUTIONCHAMBER: 0,
    UnitTypeId.EXTRACTOR: 0,
    UnitTypeId.HATCHERY: 0,
    UnitTypeId.LAIR: 0,
    UnitTypeId.HIVE: 0,
    UnitTypeId.HYDRALISKDEN: 0,
    UnitTypeId.INFESTATIONPIT: 0,
    UnitTypeId.NYDUSNETWORK: 0,
    UnitTypeId.NYDUSCANAL: 0,
    UnitTypeId.ROACHWARREN: 0,
    UnitTypeId.SPAWNINGPOOL: 0,
    UnitTypeId.SPINECRAWLER: 0,
    UnitTypeId.SPIRE: 0,
    UnitTypeId.GREATERSPIRE: 0,
    UnitTypeId.SPORECRAWLER: 0,
    UnitTypeId.ULTRALISKCAVERN: 0,

}