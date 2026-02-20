from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId

from phantom.common.constants import UNIT_COUNTER_DICT
from phantom.counters.feature_space import CounterFeatureSpace


@dataclass(frozen=True)
class CounterExample:
    enemy_type: UnitTypeId
    enemy_vector: np.ndarray
    target_vector: np.ndarray


def _normalize(vector: np.ndarray) -> np.ndarray:
    total = vector.sum()
    if total <= 0.0:
        return vector
    return vector / total


def build_training_dataset(
    feature_space: CounterFeatureSpace,
    counter_table: Mapping[UnitTypeId, Mapping[UnitTypeId, float]] = UNIT_COUNTER_DICT,
) -> list[CounterExample]:
    examples: list[CounterExample] = []
    for enemy_type in sorted(counter_table, key=lambda unit: unit.name):
        enemy_vector = feature_space.one_hot(enemy_type)
        target_vector = np.zeros(feature_space.dimension, dtype=np.float64)
        for counter_type, weight in counter_table[enemy_type].items():
            canonical = feature_space.canonical(counter_type)
            index = feature_space.index_by_unit.get(canonical)
            if index is not None:
                target_vector[index] += float(weight)
        examples.append(
            CounterExample(
                enemy_type=enemy_type,
                enemy_vector=enemy_vector,
                target_vector=_normalize(target_vector),
            )
        )
    return examples


def examples_to_matrices(examples: list[CounterExample]) -> tuple[np.ndarray, np.ndarray]:
    if not examples:
        return np.empty((0, 0)), np.empty((0, 0))
    x = np.vstack([example.enemy_vector for example in examples])
    y = np.vstack([example.target_vector for example in examples])
    return x, y
