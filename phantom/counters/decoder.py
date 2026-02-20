from collections.abc import Mapping

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId

from phantom.counters.feature_space import CounterFeatureSpace


def decode_target_distribution(
    distribution: np.ndarray,
    feature_space: CounterFeatureSpace,
    *,
    budget: float = 100.0,
    top_k: int = 10,
) -> Mapping[UnitTypeId, float]:
    non_negative = np.clip(distribution.astype(np.float64), 0.0, None)
    total = non_negative.sum()
    if total <= 0.0:
        return {}
    scaled = budget * non_negative / total
    top_indices = np.argsort(scaled)[::-1][:top_k]
    return {feature_space.unit_keys[i]: float(scaled[i]) for i in top_indices if scaled[i] > 0.0}
