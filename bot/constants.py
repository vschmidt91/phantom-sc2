from itertools import chain

from sc2.constants import (
    EQUIVALENTS_FOR_TECH_PROGRESS,
    SPEED_INCREASE_DICT,
    SPEED_UPGRADE_DICT,
)
from sc2.data import Race
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.utils import get_requirements

VERSION_FILE = "version.txt"
UNKNOWN_VERSION = "unknown_version"

WITH_TECH_EQUIVALENTS = {unit: {unit} | EQUIVALENTS_FOR_TECH_PROGRESS.get(unit, set()) for unit in UnitTypeId}

UNIT_TRAINED_FROM_WITH_EQUIVALENTS = {
    item: {equivalent for trainer in UNIT_TRAINED_FROM.get(item, []) for equivalent in WITH_TECH_EQUIVALENTS[trainer]}
    for item in UnitTypeId
}

UPGRADE_RESEARCHED_FROM_WITH_EQUIVALENTS = {
    item: WITH_TECH_EQUIVALENTS.get(UPGRADE_RESEARCHED_FROM.get(item), set()) for item in UpgradeId
}

ITEM_TRAINED_FROM_WITH_EQUIVALENTS = {**UNIT_TRAINED_FROM_WITH_EQUIVALENTS, **UPGRADE_RESEARCHED_FROM_WITH_EQUIVALENTS}

STATIC_DEFENSE_BY_RACE = {
    Race.Zerg: UnitTypeId.SPORECRAWLER,
    Race.Terran: UnitTypeId.MISSILETURRET,
    Race.Protoss: UnitTypeId.PHOTONCANNON,
}

COCOON_FIX: dict[UnitTypeId, UnitTypeId] = {
    UnitTypeId.OVERLORDCOCOON: UnitTypeId.OVERLORD,
    UnitTypeId.TRANSPORTOVERLORDCOCOON: UnitTypeId.OVERLORD,
    UnitTypeId.BANELINGCOCOON: UnitTypeId.ZERGLING,
    UnitTypeId.RAVAGERCOCOON: UnitTypeId.RAVAGER,
    UnitTypeId.BROODLORDCOCOON: UnitTypeId.CORRUPTOR,
}

RANGE_UPGRADES: dict[UnitTypeId, dict[UpgradeId, int]] = {
    UnitTypeId.COLOSSUS: {UpgradeId.EXTENDEDTHERMALLANCE: 2},
    UnitTypeId.HYDRALISK: {UpgradeId.EVOLVEGROOVEDSPINES: 1},
    UnitTypeId.PHOENIX: {UpgradeId.PHOENIXRANGEUPGRADE: 2},
    UnitTypeId.PLANETARYFORTRESS: {UpgradeId.HISECAUTOTRACKING: 1},
    UnitTypeId.MISSILETURRET: {UpgradeId.HISECAUTOTRACKING: 1},
    UnitTypeId.AUTOTURRET: {UpgradeId.HISECAUTOTRACKING: 1},
}

SPEED_UPGRADES: dict[UnitTypeId, dict[UpgradeId, float]] = {
    unit_type: {upgrade: SPEED_INCREASE_DICT[unit_type]} for unit_type, upgrade in SPEED_UPGRADE_DICT.items()
}

MACRO_INFO = {
    unit_type: {**TRAIN_INFO.get(unit_type, {}), **RESEARCH_INFO.get(unit_type, {})}
    for unit_type in set(chain(TRAIN_INFO, RESEARCH_INFO))
}

MACRO_ABILITIES = {
    trainer_type: {e["ability"] for item, e in element.items()} for trainer_type, element in MACRO_INFO.items()
}

ALL_MACRO_ABILITIES: set[AbilityId] = {
    e["ability"] for trainer_type, element in MACRO_INFO.items() for item, e in element.items()
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


SUPPLY_PROVIDED = {
    Race.Zerg: {
        UnitTypeId.OVERLORD: 8,
        UnitTypeId.HATCHERY: 6,
        # UnitTypeId.LAIR: 6,
        # UnitTypeId.HIVE: 6,
    },
    Race.Protoss: {
        UnitTypeId.PYLON: 8,
        UnitTypeId.NEXUS: 15,
    },
    Race.Terran: {
        UnitTypeId.SUPPLYDEPOT: 8,
        UnitTypeId.COMMANDCENTER: 15,
        # UnitTypeId.COMMANDCENTERFLYING: 15,
        # UnitTypeId.ORBITALCOMMAND: 15,
        # UnitTypeId.ORBITALCOMMANDFLYING: 15,
        # UnitTypeId.PLANETARYFORTRESS: 15,
    },
}

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
}

DPS_OVERRIDE = {
    UnitTypeId.BUNKER: 40,
    UnitTypeId.PLANETARYFORTRESS: 5,
}

CIVILIANS = {
    UnitTypeId.SCV,
    UnitTypeId.MULE,
    UnitTypeId.PROBE,
    UnitTypeId.LARVA,
    UnitTypeId.EGG,
    *WITH_TECH_EQUIVALENTS[UnitTypeId.WARPPRISM],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.DRONE],
    # *WITH_TECH_EQUIVALENTS[UnitTypeId.QUEEN],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.OVERLORD],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.BROODLING],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.OBSERVER],
    *CHANGELINGS,
}

UNIT_BY_TRAIN_ABILITY: dict[AbilityId, UnitTypeId] = {
    unit_element["ability"]: unit
    for trainer_element in TRAIN_INFO.values()
    for unit, unit_element in trainer_element.items()
}

UPGRADE_BY_RESEARCH_ABILITY: dict[AbilityId, UpgradeId] = {
    upgrade_element["ability"]: upgrade
    for research_element in RESEARCH_INFO.values()
    for upgrade, upgrade_element in research_element.items()
}

ITEM_BY_ABILITY = {**UNIT_BY_TRAIN_ABILITY, **UPGRADE_BY_RESEARCH_ABILITY}

GAS_BY_RACE: dict[Race, UnitTypeId] = {
    Race.Zerg: UnitTypeId.EXTRACTOR,
    Race.Protoss: UnitTypeId.ASSIMILATOR,
    Race.Terran: UnitTypeId.REFINERY,
}

REQUIREMENTS_EXCLUDE = {
    # UnitTypeId.DRONE,
    UnitTypeId.LARVA,
    # UnitTypeId.HATCHERY,
}

REQUIREMENTS_KEYS = {*UNIT_TRAINED_FROM.keys(), *UPGRADE_RESEARCHED_FROM.keys()}.difference(REQUIREMENTS_EXCLUDE)

REQUIREMENTS = {
    item: {requirement for requirement in get_requirements(item) if requirement in REQUIREMENTS_KEYS}
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
IGNORED_UNIT_TYPES = {
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
}
UNIT_COUNTER_DICT = {
    UnitTypeId.ZEALOT: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.STALKER: [UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.SENTRY: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.ADEPT: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.HIGHTEMPLAR: [UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.DARKTEMPLAR: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.ARCHON: [UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.IMMORTAL: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.COLOSSUS: [
        UnitTypeId.BROODLORD,
        UnitTypeId.CORRUPTOR,
        UnitTypeId.ROACH,
        UnitTypeId.HYDRALISK,
        UnitTypeId.ZERGLING,
    ],
    UnitTypeId.DISRUPTOR: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.PHOENIX: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.VOIDRAY: [UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.ORACLE: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.TEMPEST: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.CARRIER: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.PHOTONCANNON: [UnitTypeId.RAVAGER, UnitTypeId.QUEEN, UnitTypeId.ZERGLING],
    # UnitTypeId.PROBE: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.MARINE: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.MARAUDER: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.REAPER: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.GHOST: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.HELLION: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.SIEGETANK: [UnitTypeId.BROODLORD, UnitTypeId.ZERGLING, UnitTypeId.HYDRALISK, UnitTypeId.ROACH],
    UnitTypeId.THOR: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.WIDOWMINE: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.CYCLONE: [UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.VIKINGFIGHTER: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.VIKINGASSAULT: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.RAVEN: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.BANSHEE: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.BATTLECRUISER: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING, UnitTypeId.ROACH],
    UnitTypeId.LIBERATOR: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    # UnitTypeId.SCV: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.MEDIVAC: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.COMMANDCENTERFLYING: [UnitTypeId.CORRUPTOR],
    UnitTypeId.BARRACKSFLYING: [UnitTypeId.CORRUPTOR],
    UnitTypeId.FACTORYFLYING: [UnitTypeId.CORRUPTOR],
    UnitTypeId.STARPORTFLYING: [UnitTypeId.CORRUPTOR],
    UnitTypeId.BUNKER: [UnitTypeId.RAVAGER, UnitTypeId.QUEEN, UnitTypeId.ZERGLING],
    UnitTypeId.ZERGLING: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.ZERGLING, UnitTypeId.HYDRALISK],
    UnitTypeId.ZERGLINGBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.ZERGLING, UnitTypeId.HYDRALISK],
    UnitTypeId.BANELING: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.BANELINGBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.ROACH: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.ROACHBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.RAVAGER: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.RAVAGERBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.HYDRALISK: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.HYDRALISKBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.MUTALISK: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.CORRUPTOR: [UnitTypeId.HYDRALISK, UnitTypeId.QUEEN],
    UnitTypeId.BROODLORD: [UnitTypeId.CORRUPTOR, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.ULTRALISK: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.ULTRALISKBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.HYDRALISK, UnitTypeId.ZERGLING],
    UnitTypeId.SWARMHOSTMP: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.SWARMHOSTBURROWEDMP: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.INFESTOR: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.INFESTORBURROWED: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    UnitTypeId.VIPER: [UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    # UnitTypeId.QUEEN: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.ZERGLING, UnitTypeId.HYDRALISK],
    # UnitTypeId.QUEENBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.ROACH, UnitTypeId.ZERGLING, UnitTypeId.HYDRALISK],
    UnitTypeId.SPINECRAWLER: [UnitTypeId.RAVAGER, UnitTypeId.QUEEN, UnitTypeId.ZERGLING],
    # UnitTypeId.DRONE: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
    # UnitTypeId.DRONEBURROWED: [UnitTypeId.BROODLORD, UnitTypeId.HYDRALISK, UnitTypeId.ROACH, UnitTypeId.ZERGLING],
}


SPORE_TRIGGERS: dict[Race, set[UnitTypeId]] = {
    Race.Zerg: {
        UnitTypeId.DRONEBURROWED,
        UnitTypeId.QUEENBURROWED,
        UnitTypeId.ZERGLINGBURROWED,
        UnitTypeId.BANELINGBURROWED,
        UnitTypeId.ROACHBURROWED,
        UnitTypeId.RAVAGERBURROWED,
        UnitTypeId.HYDRALISKBURROWED,
        UnitTypeId.LURKERMP,
        UnitTypeId.LURKERMPBURROWED,
        UnitTypeId.INFESTORBURROWED,
        UnitTypeId.SWARMHOSTBURROWEDMP,
        UnitTypeId.ULTRALISKBURROWED,
        UnitTypeId.MUTALISK,
        UnitTypeId.SPIRE,
    },
    Race.Protoss: {
        UnitTypeId.STARGATE,
        UnitTypeId.ORACLE,
        UnitTypeId.VOIDRAY,
        UnitTypeId.CARRIER,
        UnitTypeId.TEMPEST,
        UnitTypeId.PHOENIX,
    },
    Race.Terran: {
        UnitTypeId.STARPORT,
        UnitTypeId.STARPORTFLYING,
        UnitTypeId.MEDIVAC,
        UnitTypeId.LIBERATOR,
        UnitTypeId.RAVEN,
        UnitTypeId.BANSHEE,
        UnitTypeId.BATTLECRUISER,
        UnitTypeId.WIDOWMINE,
        UnitTypeId.WIDOWMINEBURROWED,
    },
}
SPORE_TRIGGERS[Race.Random] = {
    *SPORE_TRIGGERS[Race.Terran],
    *SPORE_TRIGGERS[Race.Protoss],
    *SPORE_TRIGGERS[Race.Zerg],
}
