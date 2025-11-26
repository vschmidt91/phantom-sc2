from itertools import chain

from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS, SPEED_INCREASE_DICT, SPEED_UPGRADE_DICT
from sc2.data import Race, Result
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from phantom.common.utils import get_requirements
from phantom.dummy import BaseBlock, CannonRush, DummyBot

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

MIN_WEAPON_COOLDOWN = 2.0 / 22.4

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

ENERGY_GENERATION_RATE = 9 / 256  # = 0.7875 / 22.4

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

RESULT_TO_FITNESS = {
    Result.Defeat: +1.0,
    Result.Tie: 0.0,
    Result.Undecided: 0.0,
    Result.Victory: -1.0,
}

MINING_RADIUS = 1.325
MINING_RADIUS_GEYSER = 2.0

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
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
    *WITH_TECH_EQUIVALENTS[UnitTypeId.OVERSEER],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.BROODLING],
    *WITH_TECH_EQUIVALENTS[UnitTypeId.OBSERVER],
    *CHANGELINGS,
}

ENEMY_CIVILIANS = {
    UnitTypeId.LARVA,
    UnitTypeId.EGG,
    *WITH_TECH_EQUIVALENTS[UnitTypeId.BROODLING],
    UnitTypeId.SCV,
    UnitTypeId.MULE,
    UnitTypeId.PROBE,
    *WITH_TECH_EQUIVALENTS[UnitTypeId.DRONE],
    *CHANGELINGS,
}

COMBATANT_STRUCTURES = {
    UnitTypeId.SPINECRAWLER,
    UnitTypeId.SPORECRAWLER,
    UnitTypeId.PHOTONCANNON,
    UnitTypeId.BUNKER,
    UnitTypeId.MISSILETURRET,
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

MORPHERS = {
    UnitTypeId.HATCHERY,
    UnitTypeId.LAIR,
    UnitTypeId.SPIRE,
}

ITEM_BY_ABILITY = {**UNIT_BY_TRAIN_ABILITY, **UPGRADE_BY_RESEARCH_ABILITY}
TRAINER_TYPES = {
    *chain.from_iterable(UNIT_TRAINED_FROM.values()),
    *UPGRADE_RESEARCHED_FROM.values(),
    UnitTypeId.EGG,
}

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
    UnitTypeId.ZEALOT: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.ROACH: 1e4,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.STALKER: {
        UnitTypeId.ZERGLING: 3e2,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.RAVAGER: 1e0,
        UnitTypeId.ROACH: 1e0,
    },
    UnitTypeId.SENTRY: {
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ROACH: 1e0,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.ADEPT: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.HIGHTEMPLAR: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.DARKTEMPLAR: {
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.ARCHON: {
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.IMMORTAL: {
        UnitTypeId.BROODLORD: 1e3,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.ROACH: 1e0,
    },
    UnitTypeId.COLOSSUS: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.CORRUPTOR: 1e4,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.DISRUPTOR: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.ROACH: 1e1,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.PHOENIX: {
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.HYDRALISK: 3e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.VOIDRAY: {
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.HYDRALISK: 3e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.ORACLE: {
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.HYDRALISK: 3e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.TEMPEST: {
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.HYDRALISK: 3e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.CARRIER: {
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.HYDRALISK: 3e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.PHOTONCANNON: {
        UnitTypeId.RAVAGER: 1e2,
        UnitTypeId.QUEEN: 1e1,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.MARINE: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.ROACH: 3e0,
        UnitTypeId.HYDRALISK: 3e0,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.MARAUDER: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.ROACH: 1e0,
    },
    UnitTypeId.REAPER: {
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e0,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.GHOST: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.HELLION: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.ROACH: 1e4,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.SIEGETANK: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.ROACH: 1e0,
    },
    UnitTypeId.THOR: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.WIDOWMINE: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.CYCLONE: {
        UnitTypeId.ZERGLING: 1e2,
        UnitTypeId.RAVAGER: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.VIKINGFIGHTER: {
        UnitTypeId.CORRUPTOR: 1e0,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.VIKINGASSAULT: {
        UnitTypeId.CORRUPTOR: 1e0,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.RAVEN: {
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.HYDRALISK: 1e1,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.BANSHEE: {
        UnitTypeId.CORRUPTOR: 1e2,
        UnitTypeId.HYDRALISK: 1e1,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.BATTLECRUISER: {
        UnitTypeId.CORRUPTOR: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.LIBERATOR: {
        UnitTypeId.CORRUPTOR: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.MEDIVAC: {
        UnitTypeId.CORRUPTOR: 1e2,
        UnitTypeId.HYDRALISK: 1e1,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.BUNKER: {
        UnitTypeId.RAVAGER: 1e2,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.ZERGLING: {
        UnitTypeId.ROACH: 1e4,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.BANELING: {
        UnitTypeId.ROACH: 1e4,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.ROACH: {
        UnitTypeId.ROACH: 3e2,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.RAVAGER: {
        UnitTypeId.ROACH: 1e4,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.HYDRALISK: {
        UnitTypeId.ROACH: 1e4,
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.MUTALISK: {
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.CORRUPTOR: 1e1,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.CORRUPTOR: {
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.BROODLORD: {
        UnitTypeId.CORRUPTOR: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.ULTRALISK: {
        UnitTypeId.BROODLORD: 1e4,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.SWARMHOSTMP: {
        UnitTypeId.HYDRALISK: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.INFESTOR: {
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.HYDRALISK: 1e0,
        UnitTypeId.ZERGLING: 1e0,
    },
    UnitTypeId.VIPER: {
        UnitTypeId.CORRUPTOR: 1e2,
        UnitTypeId.HYDRALISK: 1e1,
        UnitTypeId.QUEEN: 1e0,
    },
    UnitTypeId.QUEEN: {
        UnitTypeId.BROODLORD: 1e2,
        UnitTypeId.ROACH: 1e2,
        UnitTypeId.ZERGLING: 1e0,
        UnitTypeId.HYDRALISK: 1e0,
    },
    UnitTypeId.SPINECRAWLER: {
        UnitTypeId.RAVAGER: 1e2,
        UnitTypeId.QUEEN: 1e1,
        UnitTypeId.ZERGLING: 1e0,
    },
}


SPORE_TRIGGERS_ZERG = {
    # UnitTypeId.DRONEBURROWED,
    # UnitTypeId.QUEENBURROWED,
    # UnitTypeId.ZERGLINGBURROWED,
    # UnitTypeId.BANELINGBURROWED,
    # UnitTypeId.ROACHBURROWED,
    # UnitTypeId.RAVAGERBURROWED,
    # UnitTypeId.HYDRALISKBURROWED,
    # UnitTypeId.LURKERMP,
    # UnitTypeId.LURKERMPBURROWED,
    # UnitTypeId.INFESTORBURROWED,
    # UnitTypeId.SWARMHOSTBURROWEDMP,
    # UnitTypeId.ULTRALISKBURROWED,
    UnitTypeId.MUTALISK,
    UnitTypeId.SPIRE,
}
SPORE_TRIGGERS_PROTOSS = {
    UnitTypeId.STARGATE,
    UnitTypeId.ORACLE,
    UnitTypeId.VOIDRAY,
    UnitTypeId.CARRIER,
    UnitTypeId.TEMPEST,
    UnitTypeId.PHOENIX,
}
SPORE_TRIGGERS_TERRAN = {
    UnitTypeId.STARPORT,
    UnitTypeId.STARPORTFLYING,
    UnitTypeId.MEDIVAC,
    UnitTypeId.LIBERATOR,
    UnitTypeId.RAVEN,
    UnitTypeId.BANSHEE,
    UnitTypeId.BATTLECRUISER,
    UnitTypeId.WIDOWMINE,
    UnitTypeId.WIDOWMINEBURROWED,
}
SPORE_TRIGGERS = {
    Race.Terran: SPORE_TRIGGERS_TERRAN,
    Race.Protoss: SPORE_TRIGGERS_PROTOSS,
    Race.Zerg: SPORE_TRIGGERS_ZERG,
    Race.Random: SPORE_TRIGGERS_TERRAN | SPORE_TRIGGERS_PROTOSS | SPORE_TRIGGERS_ZERG,
}

COCOONS = {
    UnitTypeId.BANELINGCOCOON,
    UnitTypeId.RAVAGERCOCOON,
    UnitTypeId.OVERLORDCOCOON,
    UnitTypeId.TRANSPORTOVERLORDCOCOON,
    UnitTypeId.BROODLORDCOCOON,
}

UPGRADE_RESEARCHERS = set(UPGRADE_RESEARCHED_FROM.values())

IMPOSSIBLE_TASK_COST = 1e8
HALF = Point2((0.5, 0.5))

MICRO_MAP_REGEX = "Micro AI Arena"
MAX_UNIT_RADIUS = 1.375  # Mothership
LOG_LEVEL_OPTIONS = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
REPLAY_TYPE_ENCODING = "ascii"

SPECIAL_BUILDS = {
    "Dummy": DummyBot,
    "BaseBlock": BaseBlock,
    "CannonRush": CannonRush,
}

SPORE_TIMING_ZERG = 7 * 60
SPORE_TIMING_PROTOSS = 5 * 60
SPORE_TIMING_TERRAN = 4 * 60 + 20
SPORE_TIMINGS = {
    Race.Zerg: SPORE_TIMING_ZERG,
    Race.Protoss: SPORE_TIMING_PROTOSS,
    Race.Terran: SPORE_TIMING_TERRAN,
    Race.Random: min(SPORE_TIMING_ZERG, SPORE_TIMING_PROTOSS, SPORE_TIMING_TERRAN),
}
