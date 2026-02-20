from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import chain

import numpy as np
from ares.consts import ALL_STRUCTURES, ALL_WORKER_TYPES
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.ids.unit_typeid import UnitTypeId

from phantom.common.constants import COMBATANT_STRUCTURES, UNIT_COUNTER_DICT
from phantom.common.unit_composition import UnitComposition

_DEFAULT_ALIAS_PAIRS = (
    ("VIKINGASSAULT", "VIKINGFIGHTER"),
    ("SIEGETANKSIEGED", "SIEGETANK"),
    ("WARPPRISMPHASING", "WARPPRISM"),
    ("WIDOWMINEBURROWED", "WIDOWMINE"),
    ("LURKERMPBURROWED", "LURKERMP"),
    ("SWARMHOSTBURROWEDMP", "SWARMHOSTMP"),
    ("INFESTORBURROWED", "INFESTOR"),
    ("ROACHBURROWED", "ROACH"),
    ("RAVAGERBURROWED", "RAVAGER"),
    ("QUEENBURROWED", "QUEEN"),
    ("ZERGLINGBURROWED", "ZERGLING"),
    ("BANELINGBURROWED", "BANELING"),
    ("HYDRALISKBURROWED", "HYDRALISK"),
    ("ULTRALISKBURROWED", "ULTRALISK"),
    ("DRONEBURROWED", "DRONE"),
)

_EXCLUDED_NAME_TOKENS = ("DESTRUCTIBLE", "MINERALFIELD", "VESPENEGEYSER", "XELNAGATOWER")


def _unit_type(name: str) -> UnitTypeId | None:
    return getattr(UnitTypeId, name, None)


def _default_aliases() -> dict[UnitTypeId, UnitTypeId]:
    aliases: dict[UnitTypeId, UnitTypeId] = {}
    for alias_name, canonical_name in _DEFAULT_ALIAS_PAIRS:
        alias = _unit_type(alias_name)
        canonical = _unit_type(canonical_name)
        if alias and canonical:
            aliases[alias] = canonical
    return aliases


def _is_supported(unit_type: UnitTypeId) -> bool:
    return not any(token in unit_type.name for token in _EXCLUDED_NAME_TOKENS)


def _default_unit_keys() -> tuple[UnitTypeId, ...]:
    trainables = {unit for trainer in TRAIN_INFO.values() for unit in trainer}
    table_units = set(UNIT_COUNTER_DICT).union(*UNIT_COUNTER_DICT.values())
    candidates = chain(
        trainables,
        table_units,
        COMBATANT_STRUCTURES,
        ALL_WORKER_TYPES,
        ALL_STRUCTURES,
    )
    keys = sorted({unit for unit in candidates if _is_supported(unit)}, key=lambda unit: unit.name)
    return tuple(keys)


@dataclass(frozen=True)
class CounterFeatureSpace:
    unit_keys: tuple[UnitTypeId, ...]
    index_by_unit: Mapping[UnitTypeId, int]
    alias_by_unit: Mapping[UnitTypeId, UnitTypeId]

    @classmethod
    def default(cls) -> "CounterFeatureSpace":
        unit_keys = _default_unit_keys()
        return cls(
            unit_keys=unit_keys,
            index_by_unit={unit: i for i, unit in enumerate(unit_keys)},
            alias_by_unit=_default_aliases(),
        )

    @property
    def dimension(self) -> int:
        return len(self.unit_keys)

    def canonical(self, unit_type: UnitTypeId) -> UnitTypeId:
        return self.alias_by_unit.get(unit_type, unit_type)

    def vectorize_composition(self, composition: UnitComposition) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float64)
        for unit_type, count in composition.items():
            canonical = self.canonical(unit_type)
            index = self.index_by_unit.get(canonical)
            if index is not None:
                vector[index] += float(count)
        return vector

    def vectorize_enemies(self, enemy_types: Iterable[UnitTypeId]) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float64)
        for unit_type in enemy_types:
            canonical = self.canonical(unit_type)
            index = self.index_by_unit.get(canonical)
            if index is not None:
                vector[index] += 1.0
        return vector

    def one_hot(self, unit_type: UnitTypeId) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float64)
        canonical = self.canonical(unit_type)
        index = self.index_by_unit.get(canonical)
        if index is not None:
            vector[index] = 1.0
        return vector
